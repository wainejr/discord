# Discord Bot - Acelerado

Este projeto é aberto para toda a comunidade do canal [Waine - Dev do Desempenho](https://www.youtube.com/@waine_jr).

## Descrição

O Acelerado é um bot do Discord criado para notificar sobre novos vídeos do YouTube diretamente no servidor da comunidade. Ele foi desenvolvido utilizando `discord.py`

## Rodando

Para rodar, primeiro instalar as dependências utilizando [uv](https://docs.astral.sh/uv/).

```
pip install -U uv
uv sync
```

Após isso, copiar o arquivo `.example.env` para `.env`, alterar as variáveis de ambiente, e também o arquivo `credentials.example.json` para `credentials.json` com os valores da chave OAuth do Google.

Então rodar o bot com

```
uv run acelerado
```

Na primeira vez que rodar, vai ser necessário fazer o consentimento no navegador.

## Como Contribuir

Todos são bem-vindos para contribuir com o projeto. Siga as instruções abaixo para começar:

[Documentação do Discord.py](https://discordpy.readthedocs.io/en/stable/search.html?q=choice)

1. Faça um fork do repositório.
2. Clone o seu fork:
   ```sh
   git clone https://github.com/seu-usuario/discord-bot.git
   ```

3. Crie um branch para sua feature ou correção de bug:
```sh
  git checkout -b minha-feature
```

Faça suas alterações e adicione commits:
```sh
  git add .
  git commit -m "Minha nova feature"
```
Envie suas alterações:

```sh
  git push origin minha-feature
```
Abra um Pull Request no repositório original.

## Relatar Problemas

Caso encontre algum bug, por favor, abra uma issue detalhando o máximo possível o erro encontrado. Isso nos ajudará a identificar e corrigir o problema mais rapidamente.

## Links Importantes

[Canal do YouTube](https://www.youtube.com/@waine_jr)

[Servidor do Discord](https://discord.gg/RHuhFcfzyV)

[@waine_jr no Instagram](https://instagram.com/waine_jr)

## Licença

Este projeto é licenciado sob a [MIT License](./LICENSE).

## Contato

Para dúvidas ou mais informações, entre em contato pelo servidor do Discord, comente no canal do YouTube.

Obrigado por fazer parte da nossa comunidade!
