# Security Policy

[中文版](SECURITY.zh-CN.md)

## Secrets

Never commit API keys, provider configuration containing credentials, local browser histories, patient records, or unredacted clinical notes.

The repository ignores `kg_update_system/config.deepseek.json` and related local configuration files. Start from `kg_update_system/config.example.json` and provide credentials through the `KG_LLM_API_KEY` environment variable.

## Reporting

If you discover a credential, sensitive file, or security-relevant defect in this repository, do not open a public issue containing the sensitive content. Contact the repository owner privately through GitHub first.

## Medical-data boundary

The included materials are terminology and synthetic/sample research materials. Before using the incremental workflow with local medical records, remove identifiers and follow your institution's data-governance requirements.
