# Status e próximos passos — Automação de dados imobiliários — Guarujá

> Auditoria de 22/09/2026. Esta é uma fotografia baseada em arquivos, Git, artefatos e endpoints observáveis. Nenhum build completo foi executado nesta classificação.

## Classificação

- **Estado:** coletor pausado e versionado
- **Confiança:** alta
- **Natureza:** automação Python paralela e consolidação

## Evidências observadas

- O repositório está limpo e o último commit é de abril de 2026.
- O README separa lógica principal de versões arquivadas.
- Não há evidência recente de execução validada contra o portal atual.

## Diagnóstico franco

Serve como base de conhecimento, mas precisa ser revalidado antes de voltar a coletar.

## Upgrades previstos

### P0 — preservar e tornar retomável

- Reconfirmar endpoint, termos, sessão e campos com uma única consulta autorizada.
- Registrar ambiente e amostra de resposta sem dados pessoais.
- Não usar Tor/proxy para contornar bloqueios ou limites.

### P1 — estabilizar

- Adicionar testes de parser, checkpoint, idempotência e consolidação.
- Implementar backoff, rate limit e retomada segura.
- Separar o servidor de visualização do coletor.

### P2 — evoluir

- Migrar componentes úteis para um pipeline canônico do Guarujá e arquivar variantes.

## Critério para considerar retomado

O projeto será considerado retomado quando uma coleta amostral autorizada passar por testes e gerar saída rastreável sem depender de evasão de controles.

## Prompt de retomada para o Codex

> Retome o projeto **Automação de dados imobiliários — Guarujá** nesta pasta. Leia este arquivo e o README, inspecione o Git e preserve todo trabalho local. Comece somente pelo P0, valide com evidências e não implemente P1/P2 antes de apresentar o diagnóstico atualizado.

