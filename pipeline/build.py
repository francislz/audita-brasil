"""Agrega data/raw/secoes/*.jsonl nos arquivos JSON consumidos pelo site (docs/data).

Horários: o log e o BU registram a hora LOCAL da urna. Para pôr tudo no horário
de Brasília (BRT), inferimos o fuso de cada município pela hora local em que as
urnas ficaram prontas para votação (deveria ser 08:00 BRT em todo o país): a
moda dessa hora entre as seções do município dá o deslocamento. Seções do
exterior (UF "zz") ficam fora das séries em BRT e são resumidas à parte.

Uso: python build.py
"""
import gzip
import json
import pathlib
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
SITE = ROOT / "docs" / "data"
PUB = ROOT / "data" / "secoes"  # cópia comprimida publicada no repositório

Q0, Q1 = 6 * 4, 21 * 4  # janela das séries: 06:00–21:00 BRT em intervalos de 15 min
H0, H1 = 6, 21
Q17, Q19 = 17 * 4, 19 * 4
# urna que encerrou a partir deste horário (BRT) teve a votação prorrogada; no 2º turno
# não há encerramentos entre 18:30 e 18:50, e 18:50–19:10 concentra o novo horário
PRORROGADA = 18 * 3600 + 50 * 60
CANDS = ("13", "22")
FUSO_PADRAO = {"ac": 2, "am": 1, "mt": 1, "ms": 1, "ro": 1, "rr": 1}


def segs(hhmmss):
    h, m, s = map(int, hhmmss.split(":"))
    return h * 3600 + m * 60 + s


def fmt(sec):
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def novo():
    return {
        "nsec": 0,
        "aptos": 0,
        "comp": 0,
        "votos": Counter(),
        "s2": [0] * (Q1 - Q0),
        "s1": [0] * (Q1 - Q0),
        "v17": 0,
        "v19": 0,
        "v17_t1": 0,
        "v19_t1": 0,
        "sec17": 0,
        "sec17_t1": 0,
        "sec19": 0,
        "secp": 0,  # seções com votação prorrogada (encerramento após PRORROGADA)
        "compp": 0,
        "v17p": 0,
        "semhora": 0,
        "est17": Counter(),  # estimativa proporcional dos votos após 17h por candidato
        "max17": Counter(),  # teto: min(votos após 17h, votos do candidato na seção)
        "rdv_ok": 0,
        "rdv_div": 0,
        "log_ok": 0,
        "log_div": 0,
        "sem_log": 0,
    }


def soma(a, s):
    a["nsec"] += 1
    a["aptos"] += s["aptos"]
    a["comp"] += s["comp"]
    a["votos"].update(s["votos"])
    for i, v in enumerate(s["s2"]):
        a["s2"][i] += v
    for i, v in enumerate(s["s1"]):
        a["s1"][i] += v
    for k in ("v17", "v19", "v17_t1", "v19_t1", "semhora"):
        a[k] += s[k]
    a["sec17"] += s["v17"] > 0
    a["sec19"] += s["v19"] > 0
    a["sec17_t1"] += s["v17_t1"] > 0
    if s["prorrogada"]:
        a["secp"] += 1
        a["compp"] += s["comp"]
        a["v17p"] += s["v17"]
    a["est17"].update(s["est17"])
    a["max17"].update(s["max17"])
    a["rdv_ok"] += s["rdv_ok"] is True
    a["rdv_div"] += s["rdv_ok"] is False
    a["log_ok"] += s["log_dif"] == 0
    a["log_div"] += s["log_dif"] not in (0, None)
    a["sem_log"] += s["log_dif"] is None


def final(a):
    out = dict(a)
    out["votos"] = dict(a["votos"])
    out["est17"] = {k: round(v) for k, v in a["est17"].items()}
    out["max17"] = dict(a["max17"])
    return out


def serie(r, suf, off):
    s = [0] * (Q1 - Q0)
    fora = 0
    for q, n in (r.get("votos_15min" + suf) or {}).items():
        b = int(q) + off * 4
        if Q0 <= b < Q1:
            s[b - Q0] += n
        else:
            fora += n
    return s, fora


def main():
    cfg = json.loads((RAW / "config" / "municipios.json").read_text())
    nomes = {(a["cd"], m["cd"]): m["nm"] for a in cfg["abr"] for m in a["mu"]}
    nome_uf = {a["cd"]: a["ds"] for a in cfg["abr"]}
    br_ofic = json.loads((RAW / "config" / "presidente-br.json").read_text())

    recs = defaultdict(list)
    for p in sorted((RAW / "secoes").glob("*.jsonl")):
        for line in p.read_text().splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:  # última linha de um arquivo ainda sendo escrito
                continue
            recs[r["uf"]].append(r)

    # fuso por município (moda da hora local em que a urna ficou pronta)
    fuso = {}
    for uf, rs in recs.items():
        if uf == "zz":
            continue
        horas = defaultdict(Counter)
        for r in rs:
            for k in ("pronta", "pronta_t1"):
                if r.get(k):
                    horas[r["mun"]][round(segs(r[k]) / 3600)] += 1
        for r in rs:
            c = horas.get(r["mun"])
            fuso[(uf, r["mun"])] = 8 - c.most_common(1)[0][0] if c else FUSO_PADRAO.get(uf, 0)

    if SITE.exists():
        shutil.rmtree(SITE)
    (SITE / "uf").mkdir(parents=True)
    br = novo()
    exterior = novo()
    ufs = {}
    fim2, fim1 = Counter(), Counter()  # horário do último voto da seção (BRT, 15 min)
    enc2, enc1 = Counter(), Counter()  # horário de encerramento da urna (BRT, 15 min)
    prorrogacao = []
    tardias = []
    status = Counter()
    erros = Counter()
    fora_janela = 0
    fusos = Counter()
    # comparação ecológica: votos nas seções com e sem votos após 17h
    eco = {"com": Counter(), "sem": Counter()}

    for uf in sorted(recs):
        ag_uf = novo()
        muns = defaultdict(novo)
        zonas = defaultdict(novo)
        secs_mun = defaultdict(list)
        for r in recs[uf]:
            status[r.get("status")] += 1
            for k in r:
                if k.endswith("_erro"):
                    erros[k] += 1
            if "votos" not in r:
                continue
            off = 0 if uf == "zz" else fuso[(uf, r["mun"])]
            if uf != "zz":
                fusos[off] += 1
            s2, f2 = serie(r, "", off)
            s1, f1 = serie(r, "_t1", off)
            fora_janela += f2
            v17 = sum(s2[Q17 - Q0 :])
            v19 = sum(s2[Q19 - Q0 :])
            comp = r.get("comparecimento", 0)
            votos = r["votos"]
            log_dif = None if "votos_log" not in r else comp - r["votos_log"]
            rdv = r.get("rdv")
            enc = None
            if r.get("encerramento_log") and uf != "zz":
                enc = segs(r["encerramento_log"]) + off * 3600
                enc2[enc // 900] += 1
            if r.get("encerramento_log_t1") and uf != "zz":
                enc1[(segs(r["encerramento_log_t1"]) + off * 3600) // 900] += 1
            s = {
                "aptos": r.get("aptos", 0),
                "comp": comp,
                "votos": votos,
                "s2": s2,
                "s1": s1,
                "v17": v17,
                "v19": v19,
                "v17_t1": sum(s1[Q17 - Q0 :]),
                "v19_t1": sum(s1[Q19 - Q0 :]),
                "semhora": max(0, log_dif) if log_dif is not None else comp,
                "est17": Counter({k: v17 * v / comp for k, v in votos.items()}) if comp else Counter(),
                "max17": Counter({c: min(v17, votos.get(c, 0)) for c in CANDS}),
                "rdv_ok": None if rdv is None else {k: v for k, v in votos.items() if v} == rdv,
                "log_dif": log_dif,
                "prorrogada": enc is not None and enc >= PRORROGADA,
            }
            if uf == "zz":
                soma(exterior, s)
            else:
                soma(br, s)
                soma(ag_uf, s)
                soma(muns[r["mun"]], s)
                soma(zonas[(r["mun"], r["zona"])], s)
            ult = None
            if r.get("ultimo_voto") and uf != "zz":
                ult = segs(r["ultimo_voto"]) + off * 3600
                fim2[ult // 900] += 1
            if r.get("ultimo_voto_t1") and uf != "zz":
                fim1[(segs(r["ultimo_voto_t1"]) + off * 3600) // 900] += 1
            if uf != "zz":
                eco["com" if v17 else "sem"].update(votos)
            if v17 and uf != "zz":
                tardias.append((v17, uf, r["mun"], r["zona"], r["secao"], v19, s["v17_t1"], ult))
            hr = lambda ser: [sum(ser[i : i + 4]) for i in range(0, len(ser), 4)]  # noqa: E731
            secs_mun[r["mun"]].append(
                [
                    r["zona"],
                    r["secao"],
                    s["aptos"],
                    comp,
                    votos.get("13", 0),
                    votos.get("22", 0),
                    votos.get("branco", 0),
                    votos.get("nulo", 0),
                    v17,
                    v19,
                    s["v17_t1"],
                    fmt(ult) if ult is not None else (r.get("ultimo_voto") if uf == "zz" else None),
                    hr(s2),
                    hr(s1),
                    s["rdv_ok"],
                    log_dif,
                    off,
                ]
            )

        # arquivos por UF
        mun_list = []
        for mun, a in sorted(muns.items(), key=lambda x: nomes.get((uf, x[0]), x[0])):
            zl = {z: final(za) for (m, z), za in sorted(zonas.items()) if m == mun}
            mun_list.append({"cd": mun, "nm": nomes.get((uf, mun), mun), "fuso": fuso.get((uf, mun)), **final(a), "zonas": zl})
            if a["secp"] and uf != "zz":
                prorrogacao.append({"uf": uf, "cd": mun, "nm": nomes.get((uf, mun), mun), "secp": a["secp"], "nsec": a["nsec"], "compp": a["compp"], "v17p": a["v17p"], "v17": a["v17"]})
        if uf == "zz":
            mun_list = [
                {"cd": mun, "nm": nomes.get((uf, mun), mun), "nsec": len(ss)}
                for mun, ss in sorted(secs_mun.items(), key=lambda x: nomes.get((uf, x[0]), x[0]))
            ]
        dsec = SITE / "secoes" / uf
        dsec.mkdir(parents=True, exist_ok=True)
        for mun, ss in secs_mun.items():
            (dsec / f"{mun}.json").write_text(json.dumps(ss, separators=(",", ":")))
        (SITE / "uf" / f"{uf}.json").write_text(
            json.dumps({"uf": uf, "nm": nome_uf.get(uf, uf.upper()), **final(ag_uf), "municipios": mun_list}, separators=(",", ":"))
        )
        if uf != "zz":
            ufs[uf] = {"nm": nome_uf.get(uf, uf.upper()), **final(ag_uf)}

    tardias.sort(reverse=True)
    cand = []
    for cg in br_ofic["carg"]:
        for grupo in cg.get("agr", []):
            for par in grupo["par"]:
                for c in par["cand"]:
                    cand.append({"n": c["n"], "nm": c["nmu"], "partido": par["sg"], "votos_ofic": int(c["vap"]), "pct_ofic": c["pvap"]})
    cand.sort(key=lambda c: c["n"])

    resumo = {
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fonte": "https://resultados.tse.jus.br/oficial/ele2026/arquivo-urna/3221/",
        "candidatos": cand,
        "oficial": {k: br_ofic.get(k) for k in ("dg", "hg")},
        "secoes_config": sum(1 for _ in _todas_secoes()),
        "status": dict(status),
        "erros": dict(erros),
        "fora_janela": fora_janela,
        "fusos": {str(k): v for k, v in fusos.items()},
        "brasil": final(br),
        "exterior": final(exterior),
        "ufs": ufs,
        "fim2": {str(k): v for k, v in sorted(fim2.items())},
        "fim1": {str(k): v for k, v in sorted(fim1.items())},
        "enc2": {str(k): v for k, v in sorted(enc2.items())},
        "enc1": {str(k): v for k, v in sorted(enc1.items())},
        "prorrogacao": sorted(prorrogacao, key=lambda m: -m["secp"]),
        "tardias": [
            {"v17": t[0], "uf": t[1], "mun": t[2], "nm": nomes.get((t[1], t[2]), t[2]), "zona": t[3], "secao": t[4], "v19": t[5], "v17_t1": t[6], "ultimo": fmt(t[7]) if t[7] else None}
            for t in tardias[:50]
        ],
        "eco": {k: dict(v) for k, v in eco.items()},
        "janela": {"q0": Q0, "q1": Q1},
    }
    (SITE / "resumo.json").write_text(json.dumps(resumo, ensure_ascii=False, separators=(",", ":")))

    PUB.mkdir(parents=True, exist_ok=True)
    for p in sorted((RAW / "secoes").glob("*.jsonl")):
        with p.open("rb") as fi, gzip.open(PUB / f"{p.name}.gz", "wb", compresslevel=9) as fo:
            shutil.copyfileobj(fi, fo)
    b = resumo["brasil"]
    print(f"seções: {b['nsec']} | comparecimento {b['comp']} | após 17h: {b['v17']} (1º turno: {b['v17_t1']}) | após 19h: {b['v19']}")
    print(f"prorrogadas: {b['secp']} seções em {len(prorrogacao)} municípios | comparecimento {b['compp']} | após 17h nelas: {b['v17p']}")
    print("votos:", b["votos"], "| est17:", b["est17"], "| max17:", b["max17"])


def _todas_secoes():
    from crawl import UFS, secoes

    for uf in UFS:
        yield from secoes(uf)


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    main()
