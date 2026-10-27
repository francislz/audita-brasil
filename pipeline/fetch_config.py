"""Baixa a lista de seções (config) de cada UF para o 2º turno de 2026."""
import json
import pathlib
import httpx

BASE = "https://resultados.tse.jus.br/oficial/ele2026"
PLEITO = "3221"
UFS = "ac al am ap ba ce df es go ma mg ms mt pa pb pe pi pr rj rn ro rr rs sc se sp to zz".split()
OUT = pathlib.Path(__file__).resolve().parent.parent / "data" / "raw" / "config"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with httpx.Client(headers={"User-Agent": "audita-brasil"}, timeout=60) as c:
        for path, url in [
            ("presidente-br.json", f"{BASE}/6258/dados/br/br-c0001-e006258-u.json"),
            ("municipios.json", f"{BASE}/6258/config/mun-e006258-cm.json"),
        ]:
            (OUT / path).write_bytes(c.get(url).raise_for_status().content)
        total = 0
        for uf in UFS:
            r = c.get(f"{BASE}/arquivo-urna/{PLEITO}/config/{uf}/{uf}-p00{PLEITO}-cs.json")
            r.raise_for_status()
            (OUT / f"{uf}-cs.json").write_bytes(r.content)
            n = sum(len(z["sec"]) for a in r.json()["abr"] for m in a["mu"] for z in m["zon"])
            total += n
            print(uf, n)
        print("total", total)


if __name__ == "__main__":
    main()
