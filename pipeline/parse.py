"""Decodificadores dos arquivos de urna do TSE (BU, RDV e log).

O BU e o RDV são estruturas ASN.1 codificadas em BER (especificação publicada
pelo TSE em bu.asn1 / rdv.asn1). Em vez de depender de um compilador ASN.1,
percorremos os TLVs diretamente e lemos os campos por posição, conforme a
especificação.
"""
import io
import re
import zipfile
from collections import Counter

ELEICAO_PRESIDENTE = 6258
CARGO_PRESIDENTE = 1
DIA = "25/10/2026"
DIA_T1 = "04/10/2026"


# --------------------------------------------------------------------------- BER


def _tlvs(b, o=0, end=None):
    end = len(b) if end is None else end
    while o < end:
        t = b[o]
        o += 1
        cls, cons, num = t >> 6, (t >> 5) & 1, t & 0x1F
        if num == 0x1F:
            num = 0
            while True:
                x = b[o]
                o += 1
                num = (num << 7) | (x & 0x7F)
                if not x & 0x80:
                    break
        ln = b[o]
        o += 1
        if ln & 0x80:
            n = ln & 0x7F
            ln = int.from_bytes(b[o : o + n], "big")
            o += n
        yield (cls, num), cons, b[o : o + ln]
        o += ln


def _kids(b):
    return list(_tlvs(b))


def _int(v):
    return int.from_bytes(v, "big", signed=True)


def _envelope_conteudo(raw):
    """EntidadeEnvelopeGenerico -> bytes do campo `conteudo` (OCTET STRING)."""
    (_, _, env), = _kids(raw)
    for tag, _, v in _kids(env):
        if tag == (0, 4):
            return v
    raise ValueError("envelope sem conteúdo")


def _hora(s):
    # "20261025T150152" -> "15:01:52"
    s = s.decode()
    return f"{s[9:11]}:{s[11:13]}:{s[13:15]}" if len(s) >= 15 else None


# ---------------------------------------------------------------------------- BU


def parse_bu(raw):
    bu = _kids(_kids(_envelope_conteudo(raw))[0][2])
    out = {"bu_sa": False, "bu_contingencia": False}
    urna = _kids(bu[2][2])
    out["tipo_urna"] = _int(urna[0][2])
    tag, _, v = bu[5]  # dadosSecaoSA
    if tag == (2, 0):  # dadosSecao
        k = _kids(v)
        out["abertura"] = _hora(k[0][2])
        out["encerramento"] = _hora(k[1][2])
    else:  # dadosSA: apuração pelo Sistema de Apuração (ex.: cédula)
        out["bu_sa"] = True
    for tag, cons, v in bu[6:]:
        if tag == (2, 4) and cons:  # historicoCorrespondencias: urna substituída
            out["bu_contingencia"] = True
    for tag, cons, v in bu:
        if tag[0] != 0 or tag[1] != 16 or not cons:
            continue
        for _, econs, ele in _kids(v):
            if not econs:  # não é a lista resultadosVotacaoPorEleicao
                break
            ek = _kids(ele)
            if not ek or ek[0][0] != (0, 2) or _int(ek[0][2]) != ELEICAO_PRESIDENTE:
                continue
            out["aptos"] = _int(ek[1][2])
            for tag2, _, rv in ek[2:]:
                if tag2 != (0, 16):
                    continue
                for _, _, res in _kids(rv):
                    rk = _kids(res)
                    out["comparecimento"] = _int(rk[1][2])
                    for _, _, tvc in _kids(rk[2][2]):
                        ck = _kids(tvc)
                        if _int(ck[0][2]) != CARGO_PRESIDENTE:
                            continue
                        votos = {}
                        for _, _, vv in _kids(ck[2][2]):
                            f = {t: val for t, _, val in _kids(vv)}
                            tipo = _int(f[(2, 1)])
                            qtd = _int(f[(2, 2)])
                            if tipo == 1:  # nominal
                                cod = _int(_kids(f[(2, 3)])[1][2])
                                votos[str(cod)] = qtd
                            elif tipo == 2:
                                votos["branco"] = qtd
                            elif tipo == 3:
                                votos["nulo"] = qtd
                            else:
                                votos[f"tipo{tipo}"] = votos.get(f"tipo{tipo}", 0) + qtd
                        out["votos"] = votos
    return out


# --------------------------------------------------------------------------- RDV


def parse_rdv(raw):
    """Conta os votos de Presidente registrados no RDV (um registro por eleitor)."""
    (_, _, top), = _kids(raw)
    rdv = _kids(_kids(top)[-1][2])  # EntidadeRegistroDigitalVoto
    c = Counter()
    for tag, _, v in rdv:
        if tag != (2, 1):  # eleicoes (CHOICE [1] = EleicoesVota)
            continue
        for _, _, ele in _kids(v):
            ek = _kids(ele)
            if _int(ek[0][2]) != ELEICAO_PRESIDENTE:
                continue
            for _, _, vc in _kids(ek[1][2]):
                vk = _kids(vc)
                if _int(vk[0][2]) != CARGO_PRESIDENTE:
                    continue
                for _, _, voto in _kids(vk[2][2]):
                    f = _kids(voto)
                    tipo = _int(f[0][2])
                    if tipo in (1, 2):  # legenda / nominal
                        c[f[1][2].decode()] += 1
                    elif tipo in (3, 5):
                        c["branco"] += 1
                    else:
                        c["nulo"] += 1
    return dict(c)


# --------------------------------------------------------------------------- LOG

_RE_LINHA = re.compile(rb"^(\d\d/\d\d/\d{4}) (\d\d):(\d\d):(\d\d)\t[^\t]*\t[^\t]*\t[^\t]*\t([^\t]*)", re.M)


def _vazio():
    return {
        "votos_15min": Counter(),
        "votos_log": 0,
        "bio": 0,
        "primeiro_voto": None,
        "ultimo_voto": None,
        "pronta": None,
        "encerramento_log": None,
    }


def parse_log(raw):
    """Extrai do log da urna os eventos dos dias de votação.

    Horários do log estão no fuso local da urna (ex.: Acre = Brasília - 2h).
    `votos_15min` conta os votos computados por intervalo de 15 minutos,
    indexado desde 00:00 local (chave = hora*4 + minuto//15).

    O log acumula o histórico da urna desde a carga, então também traz o
    1º turno (04/10/2026); esses campos ganham o sufixo `_t1`.
    """
    dias = {DIA.encode(): _vazio(), DIA_T1.encode(): _vazio()}
    n_logs = 0
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for name in z.namelist():
            if not name.endswith(".dat"):
                continue
            n_logs += 1
            for m in _RE_LINHA.finditer(z.read(name)):
                out = dias.get(m.group(1))
                if out is None:
                    continue
                msg = m.group(5)
                h, mi = int(m.group(2)), int(m.group(3))
                hhmmss = f"{m.group(2).decode()}:{m.group(3).decode()}:{m.group(4).decode()}"
                if msg == b"O voto do eleitor foi computado":
                    out["votos_log"] += 1
                    out["votos_15min"][h * 4 + mi // 15] += 1
                    if out["primeiro_voto"] is None or hhmmss < out["primeiro_voto"]:
                        out["primeiro_voto"] = hhmmss
                    if out["ultimo_voto"] is None or hhmmss > out["ultimo_voto"]:
                        out["ultimo_voto"] = hhmmss
                elif msg.startswith(b"Tipo de habilita") and b"biom" in msg:
                    out["bio"] += 1
                elif msg == b"Urna pronta para receber votos":
                    if out["pronta"] is None or hhmmss < out["pronta"]:
                        out["pronta"] = hhmmss
                elif msg == b"Procedimento de encerramento confirmado":
                    if out["encerramento_log"] is None or hhmmss > out["encerramento_log"]:
                        out["encerramento_log"] = hhmmss
    res = {"n_logs": n_logs}
    for dia, suf in ((DIA, ""), (DIA_T1, "_t1")):
        out = dias[dia.encode()]
        out["votos_15min"] = dict(sorted(out["votos_15min"].items()))
        res.update({k + suf: v for k, v in out.items()})
    return res
