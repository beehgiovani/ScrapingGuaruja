# ScrapingGuaruja

Protótipo de automação em Python para consultas imobiliárias e consolidação de resultados. O código experimenta divisão de tarefas entre workers, OCR, proxies configuráveis e uma interface local para acompanhar o processamento.

## Situação do projeto

Este repositório é uma ferramenta de coleta, não uma aplicação final. Os fluxos dependem do formato e das regras do portal consultado e precisam ser revalidados antes de cada uso. Paralelismo, proxy ou Tor não tornam uma coleta autorizada, estável ou anônima.

## Estrutura

- `run_parallel.py`: orquestração de workers;
- `src/automacao_imoveis.py`: fluxo principal de consulta;
- `src/consolidate_output.py` e `src/data_normalizer.py`: consolidação e normalização;
- `src/server.py`: servidor local;
- `static/`: interface de acompanhamento;
- `archive/`: versões antigas mantidas somente como referência.

## Preparação

```bash
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Copie `.env.example` para `.env` e preencha apenas as configurações necessárias. O arquivo `.env` não deve ser versionado.

## Execução experimental

```bash
.\.venv\Scripts\python.exe run_parallel.py --workers 2
```

Comece com baixa concorrência e uma amostra pequena. Verifique o portal, os logs e a saída antes de aumentar a carga.

## Limites e uso responsável

Use somente fontes públicas e acessos autorizados. Respeite termos, limites de requisição e mecanismos de proteção; não use o projeto para burlar controles de acesso. Dados pessoais e tributários devem ser minimizados, protegidos e conferidos na fonte oficial.
