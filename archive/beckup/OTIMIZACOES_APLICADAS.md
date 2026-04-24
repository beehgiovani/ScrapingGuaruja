# Otimizações de Velocidade Aplicadas

## 🚀 Foco: Máxima Velocidade (sem alterar estrutura de dados)

### 1. **HTTP Connection Pooling Agressivo**

- ✅ Reutiliza clients HTTP por shard (não cria novo client por lote)
- ✅ Connection limits otimizados: 200 conexões/host, 500 total
- ✅ HTTP/2 habilitado para multiplexing
- ✅ Keep-alive forçado com timings agressivos

### 2. **Concorrência Aumentada**

- ✅ Chunks aumentados de 20 → 50 lotes simultâneos
- ✅ Session pool aumentado de 5 → 10 sessões
- ✅ Processamento paralelo dentro de cada chunk

### 3. **Timeouts Otimizados**

- ✅ HTTP_TIMEOUT reduzido: 300s → 45s
- ✅ Timeouts específicos por operação:
  - Conexão: 10s
  - Leitura: 30s
  - Captcha: 15s

### 4. **Smart Request Skipping**

- ✅ Pula busca de certidão se `metragem` e `descricao` já preenchidos
- ✅ Pula busca de boleto se `cpf_cnpj` já preenchido
- ✅ Early return em casos de sucesso

### 5. **Locks e Sincronização**

- ✅ Removido lock global do Vigilante (usa session local)
- ✅ Atomic operations apenas onde necessário

### 6. **Backoff Otimizado**

- ✅ Base delay reduzido: 1s → 0.5s
- ✅ Max delay reduzido: 30s → 15s
- ✅ Menos tentativas em falhas críticas

### 7. **HTTP/2 Multiplexing**

- ✅ Habilitado HTTP/2 para reuso de conexões
- ✅ Pipelining implícito via httpx.AsyncClient

### 8. **Redução de I/O**

- ✅ Atomic writes otimizados
- ✅ Menos tentativas de retry em file ops

## 📊 Ganhos Esperados

| Métrica              | Antes | Depois   | Melhoria        |
| -------------------- | ----- | -------- | --------------- |
| Lotes/min            | ~50   | ~150-200 | **3-4x**        |
| Conexões simultâneas | ~20   | ~100+    | **5x**          |
| Timeout médio        | 300s  | 45s      | **85% redução** |
| Requisições/conexão  | 1-2   | 10+      | **5x**          |

## ⚠️ Observações

- **Não altera**: Estrutura de dados, formato de saída, algoritmo de parsing
- **Altera**: Velocidade de execução, uso de conexões, concorrência
- **Risco**: Maior chance de rate limiting (use com Tor ou proxies rotativos)
