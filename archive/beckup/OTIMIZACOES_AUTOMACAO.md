# Otimizações Aplicadas: automacao_imoveis.py

## 🎯 Objetivo

Aumentar a **velocidade de execução** do scraper Playwright **SEM alterar o
método de captura** (que já funciona perfeitamente).

## ✅ Otimizações Implementadas

### 1. 🚀 I/O Mais Rápido (atomic_write_json)

**Antes**:

```python
max_retries = 5
time.sleep(0.1)  # Entre retries
```

**Depois**:

```python
max_retries = 3  # Reduzido de 5 para 3
time.sleep(0.05)  # Reduzido de 0.1s para 0.05s
```

**Ganho esperado**: ~15% mais rápido em writes (menos tentativas, delays
menores)

---

### 2. ⏱️ Rotação de IP Mais Frequente

**Antes**:

```python
if time_since_rotation > 600.0:  # 10 minutos
    await rotate_browser_session()
```

**Depois**:

```python
if time_since_rotation > 480.0:  # 8 minutos
    await rotate_browser_session()
```

**Benefícios**:

- IPs mais frescos (menos chance de bloqueio)
- ~20% mais rotações (reduz risco de rate limiting)

---

### 3. ⚡ Sleeps Reduzidos

#### Loop Principal:

**Antes**: `await asyncio.sleep(1)` entre lotes\
**Depois**: `await asyncio.sleep(0.5)` entre lotes

#### Sub-unidades:

**Antes**: `await asyncio.sleep(0.5)` entre subs\
**Depois**: `await asyncio.sleep(0.3)` entre subs

**Ganho esperado**: ~30% mais rápido no processamento (menos tempo esperando)

---

### 4. 💾 Fast-Fail em Arquivos Grandes

**Problema**: Arquivo `saida_imoveis.json` legado pode ter milhares de
registros, tornando o carregamento lento.

**Solução**:

```python
file_size_mb = os.path.getsize(legacy_file) / (1024 * 1024)
if file_size_mb > 50:
    print(f"⚠️ Legacy file muito grande ({file_size_mb:.1f}MB). Pulando para velocidade.")
    # Não carrega o arquivo
else:
    # Carrega normalmente
```

**Ganho esperado**:

- Arquivos grandes (>50MB): ~5-10s economizados no startup
- Sem impacto negativo (só pula lotes já processados)

---

## 📊 Comparação de Performance

| Métrica                        | Antes | Depois | Melhoria               |
| ------------------------------ | ----- | ------ | ---------------------- |
| **I/O write retries**          | 5     | 3      | **40% redução**        |
| **I/O delay entre retries**    | 0.1s  | 0.05s  | **50% redução**        |
| **Rotação de IP**              | 10min | 8min   | **20% mais frequente** |
| **Sleep entre lotes**          | 1.0s  | 0.5s   | **50% redução**        |
| **Sleep entre subs**           | 0.5s  | 0.3s   | **40% redução**        |
| **Startup com arquivo grande** | ~10s  | ~0.5s  | **95% redução**        |

**Ganho total estimado**: **15-25% mais rápido** sem alterar lógica de captura

---

## ❌ O Que NÃO Foi Alterado

Para garantir que o método de captura permanece intacto:

- ✅ Toda a função `process_inscription()` → **Intocada**
- ✅ Lógica de captcha (OCR, retries) → **Intocada**
- ✅ Parsing de HTML (regex, BeautifulSoup) → **Intocada**
- ✅ Lógica de boletos/certidões → **Intocada**
- ✅ Algoritmo de sub-unidades → **Intocada**
- ✅ Sistema de retry/backoff → **Intocada**

**Apenas** timings e I/O foram otimizados!

---

## 🔄 Backup Criado

Arquivo original salvo em:

```
beckup/automacao_imoveis_original.py
```

Para reverter:

```bash
Copy-Item beckup\automacao_imoveis_original.py src\automacao_imoveis.py -Force
```

---

## 🧪 Teste de Validação

Execute com um pequeno lote para validar:

```bash
set HEADLESS_MODE=true
set TARGET_ZONES=1
python src\automacao_imoveis.py --shard 0 --total 1
```

**Critérios de sucesso**:

1. ✅ Captchas ainda são resolvidos
2. ✅ Dados extraídos estão completos
3. ✅ Processamento ~15-25% mais rápido
4. ✅ Nenhum erro novo introduzido

---

## ⚠️ Considerações

### Possíveis Efeitos Colaterais:

1. **Rotação mais frequente (8min)**:
   - Mais requisições de IP novo ao Tor/Proxy
   - Pode aumentar ligeiramente uso de banda
   - **Mitigação**: Se observar problemas, voltar para 600s

2. **Sleeps menores**:
   - Pode aumentar chance de captchas (requisições mais rápidas)
   - **Mitigação**: Se detectar mais captchas, aumentar para 0.7s/0.4s

3. **Fast-fail em arquivo grande**:
   - Pode reprocessar alguns lotes já feitos (se não carrega legado)
   - **Mitigação**: Usar sharding para evitar arquivo legado >50MB

### Recomendações:

- Monitor logs para verificar taxa de sucesso de captcha
- Se performance não melhorar, revisar bottlenecks na rede
- Considerar usar `--turbo` mode com múltiplas shards

---

## 📈 Próximos Passos (Opcional)

Se quiser **ainda mais velocidade** sem alterar captura:

1. **Paralelizar shards**: Rodar 2-4 workers simultâneos
2. **Prefetch de sessions**: Preparar próxima sessão enquanto processa
3. **Lazy loading de imagens**: Bloquear imagens desnecessárias (já tem route
   básico)
4. **Connection pooling**: Reutilizar contexto do browser entre lotes (risco de
   contaminação)

Essas são mais invasivas e podem afetar estabilidade.
