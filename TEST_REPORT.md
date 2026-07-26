# Relatório de validação — VAELITH Plataforma Operacional v5

**Data:** 26 de julho de 2026  
**Resultado automatizado:** 37 de 37 verificações aprovadas

## Escopo validado

- inicialização da API e rota de saúde;
- login demonstrativo e cookie de sessão HTTP-only;
- isolamento dos empreendimentos por usuário;
- carregamento do empreendimento demonstrativo;
- inventário dos sete arquivos de teste;
- execução da Compatibilização Geral como análise principal;
- reconhecimento de IFCs, orçamento e cronograma;
- geração da matriz projeto × escopo × orçamento × cronograma;
- preparação dos modelos IFC para a maquete;
- geração de ocorrências rastreáveis;
- atualização e persistência do tratamento das ocorrências;
- aprovação da versão-base;
- cadastro e análise complementar de mudança;
- salvamento de ocorrência proveniente do pré-clash 3D;
- exportações em JSON, Excel, Word e PDF;
- presença dos arquivos essenciais da aplicação;
- validação sintática do Python e do JavaScript;
- balanceamento básico do CSS e ausência de IDs HTML duplicados.

## Estado limpo entregue

O banco incluído no pacote foi reinicializado após os testes e contém:

- 1 usuário demonstrativo;
- 1 empreendimento demonstrativo;
- 7 arquivos de engenharia de exemplo;
- 1 análise de compatibilização geral;
- 14 ocorrências iniciais;
- nenhuma mudança cadastrada;
- nenhuma sessão ativa;
- versão-base ainda não aprovada.

## Validação visual

As telas institucional, login e dashboard foram renderizadas estaticamente. A navegação completa com servidor foi validada pelas rotas e testes de integração. O navegador automatizado deste ambiente impediu a navegação para o servidor local por uma política administrativa do sandbox; isso não foi causado por erro da aplicação.

## Limitações conhecidas da beta

1. O pré-clash 3D usa caixas envolventes e deve ser tratado como triagem. A análise geométrica exata ainda precisa do motor IfcOpenShell/IfcClash no servidor.
2. Arquivos RVT e DWG são recebidos e catalogados, mas devem ser exportados para IFC para análise geométrica nesta versão.
3. PDF e DWG 2D ainda não possuem sobreposição e conferência dimensional avançada automática.
4. O cruzamento de escopo, orçamento e cronograma é preliminar e precisa de validação profissional.
5. O caminho crítico e o custo definitivo de impacto ainda não são calculados como engenharia contratual conclusiva.
6. O armazenamento local e o SQLite são adequados ao piloto. A produção deverá utilizar banco gerenciado, armazenamento privado, fila de processamento, backup, antivírus e auditoria.

## Conclusão

A versão v5 está apta para uso piloto local e validação com projetos controlados. Ela não deve ser apresentada como motor BIM definitivo nem utilizada para liberar execução sem revisão dos responsáveis técnicos.
