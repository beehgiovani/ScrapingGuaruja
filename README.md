# Automação de Imóveis

Este projeto contém scripts para automação de coleta e processamento de dados imobiliários.

## Estrutura do Projeto

- `automacao_imoveis.py`: Script principal de automação.
- `server.py`: Servidor backend.
- `proxy_scraper.py`, `proxy_config.py`: Gerenciamento de proxies.
- `tor_manager.py`: Integração com rede Tor.
- `static/`: Arquivos estáticos front-end.

## Instalação

1. Configure o ambiente virtual:
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   venv\Scripts\activate     # Windows
   ```

2. Instale as dependências:
   ```bash
   pip install -r requirements.txt
   ```

## Uso

Execute o script principal:
```bash
python automacao_imoveis.py
```
