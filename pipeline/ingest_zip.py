"""Processa os pacotes em massa do TSE (um .zip por UF) em vez de baixar seção a seção.

O TSE publica, alguns dias após cada turno, os arquivos de urna em
https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/arqurnatot/
    bu_imgbu_logjez_rdv_vscmr_2026_2t_<UF>.zip

Este script baixa (se preciso) cada pacote, decodifica BU/RDV/log com os
mesmos parsers do crawl.py e grava data/raw/secoes/<uf>.jsonl no mesmo formato.

Uso: python ingest_zip.py [uf ...] [--keep-zip]
"""
import argparse
import json
import pathlib
import re
import sys
import zipfile
from concurrent.futures import ProcessPoolExecutor

import httpx

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import parse  # noqa: E402
from crawl import OUT, ROOT, UFS, secoes  # noqa: E402

CDN = "https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/arqurnatot"
ZIPS = ROOT / "data" / "raw" / "zips"
# o03221ac0107400040001-bu.dat -> pleito, uf, município, zona, seção, tipo
NOME = re.compile(r"o0(\d{4})([a-z]{2})(\d{5})(\d{4})(\d{4})-(bu|rdv|log)\.(?:dat|jez)$")


def baixar(uf):
    ZIPS.mkdir(parents=True, exist_ok=True)
    dest = ZIPS / f"2t_{uf}.zip"
    if dest.exists():
        return dest
    url = f"{CDN}/bu_imgbu_logjez_rdv_vscmr_2026_2t_{uf.upper()}.zip"
    tmp = dest.with_suffix(".part")
    with httpx.stream("GET", url, timeout=120, follow_redirects=True) as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    tmp.rename(dest)
    return dest


def _processa(args):
    zpath, uf, mun, zona, sec, membros = args
    rec = {"uf": uf, "mun": mun, "zona": zona, "secao": sec, "status": "Totalizada", "hash": None}
    rec["arquivos"] = sorted(membros)
    with zipfile.ZipFile(zpath) as z:
        for tp, fn in (("bu", parse.parse_bu), ("rdv", parse.parse_rdv), ("log", parse.parse_log)):
            if tp not in membros:
                continue
            try:
                val = fn(z.read(membros[tp]))
            except Exception as e:
                rec[f"{tp}_erro"] = f"{type(e).__name__}: {e}"
                continue
            if tp == "rdv":
                rec["rdv"] = val
            else:
                rec.update(val)
    return rec


def ingerir(uf, pool):
    zpath = baixar(uf)
    grupos = {}
    with zipfile.ZipFile(zpath) as z:
        for nome in z.namelist():
            m = NOME.search(nome)
            if m and m.group(1) == "3221":
                grupos.setdefault(m.group(3, 4, 5), {})[m.group(6)] = nome
    esperadas = set(secoes(uf))
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{uf}.jsonl"
    feitas = set()
    if out.exists():
        feitas = {(r["mun"], r["zona"], r["secao"]) for r in map(json.loads, out.read_text().splitlines())}
    tarefas = [(str(zpath), uf, *k, v) for k, v in grupos.items() if k not in feitas]
    with out.open("a") as f:
        for rec in pool.map(_processa, tarefas, chunksize=64):
            f.write(json.dumps(rec, separators=(",", ":")) + "\n")
    faltam = esperadas - feitas - set(grupos)
    print(f"[{uf}] {len(tarefas)} seções do pacote, {len(faltam)} esperadas ausentes", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ufs", nargs="*", default=UFS)
    ap.add_argument("--keep-zip", action="store_true")
    a = ap.parse_args()
    with ProcessPoolExecutor(max_workers=8) as pool:
        for uf in a.ufs:
            ingerir(uf, pool)
            if not a.keep_zip:
                (ZIPS / f"2t_{uf}.zip").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
