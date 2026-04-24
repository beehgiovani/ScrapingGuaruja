# Automação de Dados Imobiliários

Plataforma escalável para extração e processamento paralelo de dados imobiliários e de IPTU, utilizando arquitetura multi-worker distribuída com rotação nativa de IPs através do Tor e suporte a proxies customizados.

## 🚀 Estrutura do Projeto (Em Foco)

O repositório foi organizado para isolar a lógica principal ("em foco") de arquivos legados de backup (agora na pasta `archive/`).

- **`run_parallel.py`**: O orquestrador principal da aplicação. Responsável por inicializar os bots (workers) paralelamente, dividir a carga de trabalho (sharding) e gerenciar os logs.
- **`src/automacao_imoveis.py`**: Bot principal (Worker). Executa a extração em um fragmento específico (shard) e realiza todo o ciclo de vida (scraping, OCR de captcha, parsing, e salvamento atômico).
- **`src/tor_manager.py`**: Gerenciador inteligente da rede Tor local. Garante anonimização das chamadas provendo portas para SOCKS isoladas por credencial, criando um túnel seguro para evitar bloqueios IP.
- **`src/fast_scraper_v7_turbo.py`**: Versão alternativa ou otimizada de alta velocidade para raspagem.
- **`src/server.py`**: Servidor (FastAPI) para interação e consumo dos dados processados via endpoints.

## 🛠️ Configuração Inicial

Por questões de segurança, **dados sensíveis não são versionados** no código. Utilize um arquivo `.env` local.

1. **Configure o Ambiente Virtual**:
   ```bash
   python -m venv venv
   # No Windows:
   venv\Scripts\activate
   # No Linux/Mac:
   source venv/bin/activate
   ```

2. **Instale as dependências**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure as Variáveis de Ambiente**:
   Faça uma cópia do arquivo de exemplo de ambiente e o renomeie:
   ```bash
   cp .env.example .env
   ```
   Abra o arquivo `.env` gerado e preencha com suas senhas reais e credenciais (como a senha de autenticação do seu servidor Tor, credenciais de proxy HTTP se utilizados, etc). O código vai ler do `.env` graças à biblioteca `python-dotenv`.

## ▶️ Uso

A melhor forma de iniciar a extração massiva é utilizar o Orquestrador em modo paralelo:

```bash
# Inicia a raspagem dividindo em N workers paralelos
python run_parallel.py --workers 5
```

Você também pode subir o servidor web:
```bash
python src/server.py
```

## 🔒 Segurança para GitHub
As senhas chumbadas foram completamente removidas nas últimas atualizações. Certifique-se de **nunca comitar seu arquivo `.env`** para o repositório público (ele já está no `.gitignore` por precaução). O projeto pode ser subido e disponibilizado publicamente sem problemas de exposição de credenciais.
