# Guia Rápido de Git e GitHub

Este guia contém os comandos essenciais para você salvar e enviar as alterações do seu projeto para o GitHub.

## 1. Verificar o que mudou (Status)
Antes de começar, é bom verificar quais arquivos foram modificados.
```bash
git status
```
*Arquivos em vermelho não estão prontos para envio. Arquivos em verde já foram adicionados.*

## 2. Preparar arquivos para envio (Add)
Para adicionar **todas** as alterações feitas no projeto:
```bash
git add .
```

## 3. Salvar as alterações (Commit)
Crie um "pacote" com as suas alterações e uma mensagem explicando o que foi feito.
Substitua a mensagem entre aspas pelo que você realmente fez.
```bash
git commit -m "Descreva aqui o que você alterou"
```
*Exemplo: `git commit -m "Adiciona novo filtro de busca"`*

## 4. Enviar para o GitHub (Push)
Envie as alterações salvas no seu computador para o repositório online.
```bash
git push
```

---

## Resumo do Fluxo de Trabalho (Cheat Sheet)

Sempre que quiser atualizar o GitHub com suas mudanças, rode a sequência:

1. `git add .`
2. `git commit -m "Sua mensagem"`
3. `git push`

---

## Dicas Extras

### Pegar atualizações do GitHub (Pull)
Se você (ou outra pessoa) alterou arquivos direto no site do GitHub, você precisa baixá-los para o seu computador antes de enviar novas coisas:
```bash
git pull
```

### Resolver conflitos
Se o `git push` falhar avisando que há mudanças remotas, faça um `git pull` primeiro.
