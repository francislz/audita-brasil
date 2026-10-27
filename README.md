# Audita Brasil: 2º turno de 2026

Site estático que mostra, a partir dos arquivos de urna publicados pelo TSE, quantos
votos foram registrados em cada horário no 2º turno de 25/10/2026, com atenção
especial à prorrogação da votação das 17h para as 19h.

## Estrutura

```
pipeline/
  fetch_config.py   lista de seções por UF + resultado oficial (TSE)
  crawl.py          baixa BU, RDV e log de cada seção e extrai estatísticas
  ingest_zip.py     alternativa: processa os pacotes .zip por UF do TSE (quando publicados)
  parse.py          decodificadores de BU, RDV (ASN.1/BER) e log da urna
  build.py          agrega tudo e gera os JSON do site em docs/data/
data/
  raw/config/       configuração baixada do TSE (seções, municípios, resultado)
  secoes/<uf>.jsonl.gz   uma linha por seção com tudo o que foi extraído
docs/               o site (index.html, app.js, style.css, data/)
```

## Como reproduzir

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python pipeline/fetch_config.py
.venv/bin/python pipeline/crawl.py          # ~2 milhões de requisições; respeita o limite do TSE
# ou, quando o TSE publicar os pacotes do 2º turno:
.venv/bin/python pipeline/ingest_zip.py
.venv/bin/python pipeline/build.py
python3 -m http.server -d docs 8000         # abrir http://localhost:8000
```

O servidor do TSE (Akamai) responde 429 se receber requisições demais; o
`crawl.py` reduz a taxa sozinho e é retomável (pode ser interrompido e rodado de novo).

## Publicar no GitHub Pages

Site publicado em https://francislz.github.io/audita-brasil/

1. Faça push deste diretório para o GitHub.
2. Em *Settings → Pages*, escolha *Deploy from a branch*, branch `main`, pasta `/docs`.
3. Para atualizar os dados: rode `pipeline/build.py` de novo, faça commit de `docs/data/` e `data/secoes/` e push.

## Campos de `data/secoes/<uf>.jsonl.gz`

| campo | significado |
|---|---|
| `uf`, `mun`, `zona`, `secao` | identificação da seção (códigos do TSE) |
| `hash` | diretório dos arquivos da seção no TSE |
| `aptos`, `comparecimento`, `votos` | do Boletim de Urna (Presidente; `13`, `22`, `branco`, `nulo`) |
| `rdv` | contagem dos votos de Presidente no RDV |
| `abertura`, `encerramento` | primeiro e último voto segundo o BU (hora local) |
| `votos_15min` | votos computados por intervalo de 15 min (chave = hora*4 + min//15, hora local) |
| `votos_log`, `bio`, `pronta`, `primeiro_voto`, `ultimo_voto`, `encerramento_log` | extraídos do log |
| `*_t1` | os mesmos campos do log para o 1º turno (04/10/2026), que o log da urna também guarda |
| `tipo_urna`, `bu_contingencia`, `bu_sa` | urna de seção (1) ou de reserva (4), substituição, apuração por cédula |

## Limitações

- O voto é secreto: nenhum arquivo diz em quem votou quem votou depois das 17h. O site
  mostra uma estimativa proporcional e um teto matemático, explicados na página.
- Horários do log são locais; o fuso de cada município é inferido pela hora de abertura.
- Quando a urna é substituída, o log publicado pode cobrir só a urna de reserva; esses votos
  aparecem como "sem horário".
