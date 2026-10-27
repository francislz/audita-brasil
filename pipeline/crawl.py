"""Baixa BU, RDV e log de todas as seções do 2º turno de 2026 e extrai estatísticas.

Os arquivos brutos não são guardados por padrão (o log sozinho soma ~90 GB);
para cada seção gravamos uma linha JSON em data/raw/secoes/<uf>.jsonl.
O processo é retomável: seções já gravadas são puladas.

O servidor do TSE (Akamai) devolve 429 quando recebe requisições demais. Um
limitador adaptativo controla a taxa: cada 429 pausa todos os downloads e corta
a taxa pela metade; sem erros, a taxa volta a subir devagar.

Uso: python crawl.py [uf ...] [--rate 80] [--max-rate 200] [--keep-raw]
"""
import argparse
import asyncio
import json
import pathlib
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import httpx

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import parse  # noqa: E402

BASE = "https://resultados.tse.jus.br/oficial/ele2026/arquivo-urna/3221"
ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG = ROOT / "data" / "raw" / "config"
OUT = ROOT / "data" / "raw" / "secoes"
RAW = ROOT / "data" / "raw" / "urna"
UFS = "ac al am ap ba ce df es go ma mg ms mt pa pb pe pi pr rj rn ro rr rs sc se sp to zz".split()
PARSERS = {"bu": parse.parse_bu, "rdv": parse.parse_rdv, "log": parse.parse_log}


def secoes(uf):
    cfg = json.loads((CONFIG / f"{uf}-cs.json").read_text())
    for a in cfg["abr"]:
        for m in a["mu"]:
            for z in m["zon"]:
                for s in z["sec"]:
                    if "nsp" in s:  # seção agregada: votos estão na seção principal
                        continue
                    yield m["cd"], z["cd"], s["ns"]


class Limiter:
    """Limitador de requisições/s com aumento aditivo e redução multiplicativa."""

    def __init__(self, rate, max_rate):
        self.rate, self.max_rate = rate, max_rate
        self.next = time.monotonic()
        self.paused_until = 0.0
        self.lock = asyncio.Lock()
        self.ok = 0

    async def wait(self):
        async with self.lock:
            now = time.monotonic()
            t = max(self.next, self.paused_until, now)
            self.next = t + 1 / self.rate
        await asyncio.sleep(t - now)

    def success(self):
        self.ok += 1
        if self.ok >= 200 and self.rate < self.max_rate:
            self.rate = min(self.max_rate, self.rate + 2)
            self.ok = 0

    def throttled(self, pause):
        now = time.monotonic()
        if now >= self.paused_until:  # conta um evento por pausa, não por requisição
            self.rate = max(5, self.rate / 2)
            self.paused_until = now + pause
            self.ok = 0
            print(f"429 recebido: pausa de {pause}s, taxa -> {self.rate:.0f} req/s", flush=True)


async def get(client, lim, url, tries=8):
    for i in range(tries):
        await lim.wait()
        try:
            r = await client.get(url)
        except httpx.HTTPError:
            if i == tries - 1:
                raise
            await asyncio.sleep(2**i)
            continue
        if r.status_code == 404:
            return None
        if r.status_code in (429, 403):
            lim.throttled(60 * (i + 1))
            continue
        if r.status_code >= 500 and i < tries - 1:
            await asyncio.sleep(2**i)
            continue
        r.raise_for_status()
        lim.success()
        return r.content
    raise RuntimeError(f"desisti após {tries} tentativas: {url}")


def _parse(tp, raw):
    try:
        return tp, PARSERS[tp](raw), None
    except Exception as e:  # registra e segue; a seção aparece como erro nas estatísticas
        return tp, None, f"{type(e).__name__}: {e}"


async def secao(client, lim, pool, uf, mun, zona, sec, keep_raw):
    rec = {"uf": uf, "mun": mun, "zona": zona, "secao": sec}
    d = f"{BASE}/dados/{uf}/{mun}/{zona}/{sec}"
    aux = await get(client, lim, f"{d}/p003221-{uf}-m{mun}-z{zona}-s{sec}-aux.json")
    if aux is None:
        rec["status"] = "sem-aux"
        return rec
    aux = json.loads(aux)
    rec["status"] = aux.get("st")
    hashes = aux.get("hashes", [])
    tot = [h for h in hashes if h.get("st") == "Totalizado"] or hashes
    rec["n_hashes"] = len(hashes)
    if not tot:
        return rec
    h = tot[-1]
    rec["hash_st"] = h.get("st")
    rec["hash"] = h["hash"]
    arqs = {a["tp"]: a["nm"] for a in h.get("arq", [])}
    rec["arquivos"] = sorted(arqs)
    loop = asyncio.get_running_loop()
    for tp in ("bu", "rdv", "log"):
        if tp not in arqs:
            continue
        raw = await get(client, lim, f"{d}/{h['hash']}/{arqs[tp]}")
        if raw is None:
            rec[f"{tp}_erro"] = "404"
            continue
        if keep_raw and tp != "log":
            p = RAW / uf / arqs[tp]
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(raw)
        _, val, err = await loop.run_in_executor(pool, _parse, tp, raw)
        if err:
            rec[f"{tp}_erro"] = err
        elif tp == "rdv":
            rec["rdv"] = val
        else:
            rec.update(val)
    return rec


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ufs", nargs="*", default=UFS)
    ap.add_argument("--rate", type=float, default=80, help="requisições/s iniciais")
    ap.add_argument("--max-rate", type=float, default=200)
    ap.add_argument("--workers", type=int, default=64)
    ap.add_argument("--keep-raw", action="store_true")
    a = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    q = asyncio.Queue()
    files = {}
    for uf in a.ufs:
        out = OUT / f"{uf}.jsonl"
        done = set()
        if out.exists():
            for line in out.read_text().splitlines():
                r = json.loads(line)
                done.add((r["mun"], r["zona"], r["secao"]))
        todo = [s for s in secoes(uf) if s not in done]
        print(f"[{uf}] {len(done)} prontas, {len(todo)} a baixar", flush=True)
        for s in todo:
            q.put_nowait((uf, *s))
        files[uf] = out.open("a")
    total = q.qsize()

    lim = Limiter(a.rate, a.max_rate)
    n, falhas, t0 = 0, 0, time.time()
    limits = httpx.Limits(max_connections=a.workers, max_keepalive_connections=a.workers)
    with ProcessPoolExecutor(max_workers=8) as pool:
        async with httpx.AsyncClient(
            headers={"User-Agent": "audita-brasil (auditoria cidada)"}, timeout=90, limits=limits
        ) as client:

            async def worker():
                nonlocal n, falhas
                while True:
                    try:
                        uf, mun, zona, sec = q.get_nowait()
                    except asyncio.QueueEmpty:
                        return
                    try:
                        rec = await secao(client, lim, pool, uf, mun, zona, sec, a.keep_raw)
                    except Exception as e:
                        falhas += 1
                        print(f"[{uf}] falha {mun}/{zona}/{sec}: {e!r}", flush=True)
                        continue  # fica de fora do arquivo; nova execução tenta de novo
                    files[uf].write(json.dumps(rec, separators=(",", ":")) + "\n")
                    n += 1
                    if n % 2000 == 0:
                        for f in files.values():
                            f.flush()
                        el = time.time() - t0
                        print(
                            f"{n}/{total} {n / el:.1f} seções/s, taxa {lim.rate:.0f} req/s, "
                            f"falhas {falhas}, faltam ~{(total - n) / (n / el) / 60:.0f} min",
                            flush=True,
                        )

            await asyncio.gather(*(worker() for _ in range(a.workers)))
    for f in files.values():
        f.close()
    print(f"concluído: {n} seções em {time.time() - t0:.0f}s, {falhas} falhas", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
