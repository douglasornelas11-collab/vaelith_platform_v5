# Arquitetura da VAELITH v5

## Decisão de produto
A VAELITH é um software web. O site institucional apresenta o produto; a aplicação autenticada concentra empreendimentos, arquivos, compatibilização, maquete 3D, interferências, orçamento, cronograma, revisões, mudanças e relatórios.

## Fluxo implementado
1. Criar empreendimento.
2. Definir disciplinas esperadas.
3. Enviar projetos, escopo, memoriais, orçamento e cronograma.
4. Classificar disciplina, revisão e categoria.
5. Executar compatibilização geral.
6. Visualizar a maquete IFC e executar pré-clash.
7. Salvar, atribuir e tratar ocorrências.
8. Aprovar a versão-base.
9. Cadastrar e analisar mudanças posteriores.

## Piloto local
- FastAPI.
- SQLite.
- Armazenamento em disco privado pelo servidor.
- Sessão por cookie HTTP-only.
- Processamento de IFC textual, XLSX/CSV, PDF, DOCX e imagens.
- Maquete no navegador com Three.js e web-ifc.
- Pré-clash por caixas envolventes.

## Produção online
Substituir:
- SQLite por PostgreSQL.
- pasta `data/uploads` por armazenamento S3 privado.
- processamento síncrono por fila de tarefas.
- sessão local por autenticação gerenciada ou serviço próprio com recuperação de senha e MFA.
- pré-clash por caixas envolventes por motor geométrico IfcOpenShell/IfcClash.

## Limitações declaradas
- RVT e DWG são armazenados, mas precisam de IFC para análise geométrica.
- PDF e DWG 2D exigem motores especializados para sobreposição e comparação dimensional avançada.
- As regras semânticas são triagens, não substituem coordenação e responsabilidade técnica.
- Os valores reconhecidos no orçamento não são automaticamente custo de impacto.
