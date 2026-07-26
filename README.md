# VAELITH LABS — Plataforma Operacional Piloto v5

## O que esta versão é
Uma aplicação web utilizável no computador ou em um servidor. O núcleo principal é a **Compatibilização Geral do Empreendimento**. O módulo de mudanças é complementar e utiliza a versão-base compatibilizada.

## Executar no Windows
1. Extraia o pacote.
2. Execute `start.bat`.
3. O navegador abrirá em `http://localhost:8080/login`.

## Login demonstrativo
- E-mail: `demo@vaelithlabs.com.br`
- Senha: `vaelith`

Também é possível criar uma conta local pela tela de acesso.

## O que funciona
- criação e configuração de empreendimentos;
- login e separação dos projetos por usuário;
- upload de IFC, RVT, DWG, PDF, Word, Excel, CSV, MPP e imagens;
- classificação de disciplina, revisão e categoria;
- leitura de IFC, XLSX/CSV, PDF, DOCX e imagens;
- inventário e controle de revisões;
- comparação de revisões IFC e documentos;
- cruzamento preliminar projeto × escopo × orçamento × cronograma;
- identificação de arquivos, disciplinas e informações ausentes;
- maquete IFC no navegador;
- pré-clash por envelopes geométricos;
- salvamento e tratamento de interferências;
- aprovação da versão-base;
- cadastro e análise de mudanças posteriores;
- exportação em PDF, Word, Excel e JSON.

## O que ainda não deve ser tratado como automático definitivo
- clash geométrico exato de produção;
- leitura geométrica nativa de RVT e DWG;
- compatibilização dimensional avançada de plantas PDF/DWG;
- cálculo definitivo de custo e caminho crítico;
- aplicação automática de uma mudança no modelo BIM.

## Dados
O piloto salva banco e arquivos dentro da pasta `data`. Para uso real em nuvem, use PostgreSQL, armazenamento privado S3, backup, logs, antivírus e políticas de acesso.
