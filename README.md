# Reg4RWE

Public FDA reviews and EMA assessment reports, read as regulatory feedback on real-world evidence. The navigator lets you move through how the evidence was used, the question it was asked to answer, the setting, and what the regulator accepted or criticised.

Some records still need a line-by-line check. Those are marked **Needs manual review**. FDA’s own published example tables are included and compared with this corpus.

## Open the app

The hosted app is at [https://www.reg4rwe.com](https://www.reg4rwe.com). [reg4rwe.com](https://reg4rwe.com) redirects there.

To run it locally:

```bash
python3 serve.py
```

Then open http://127.0.0.1:8765.

## Appraise your own design

The skill `reg4rwe` holds a proposed study against this feedback. It returns the closest precedents, the regulator’s words where a passage was extracted, and the feedback that recurs across those precedents. It then asks the assistant to appraise the design from those points only.

Activate it by copying `skills/reg4rwe` into the skills folder your client reads:

| Client | Folder |
| --- | --- |
| Claude Code | `.claude/skills/reg4rwe` or `~/.claude/skills/reg4rwe` |
| Cursor | `.agents/skills/reg4rwe` in this repository, or `~/.cursor/skills/reg4rwe` |
| GitHub Copilot | `.github/skills/reg4rwe` |
| Grok | the same skill file, plus the MCP server below if the client accepts MCP |

Copies for Claude Code, Cursor, and Copilot are already in this repository (`.claude/skills`, `.agents/skills`, and `.github/skills`).

### MCP server

The server speaks the Model Context Protocol on standard input and output. The tool is `appraise_rwe_design`. Point the client at this checkout:

```json
{
  "mcpServers": {
    "reg4rwe": {
      "command": "python3",
      "args": ["mcp/server.py"],
      "cwd": "/absolute/path/to/Reg4RWE"
    }
  }
}
```

The same block works in Claude Desktop (`claude_desktop_config.json`), Claude Code, Cursor, and VS Code Copilot when those clients are given an MCP server. A copy of the block is in `mcp/claude_desktop_config.example.json`.

### ChatGPT

In a custom GPT, add an action from `mcp/openapi.yaml`. The action posts the design to `https://www.reg4rwe.com/api/appraise`. In ChatGPT developer mode, you can instead attach the MCP server above. Ask it to appraise the study. The reply should list precedents and the feedback the regulators recorded.

The same POST works for any client that can call an HTTP endpoint:

```bash
curl -s https://www.reg4rwe.com/api/appraise \
  -H "Content-Type: application/json" \
  -d '{"design":"A single-arm trial in a rare disease, with an external control arm built from a disease registry."}'
```

## Usage log

Every appraisal is logged: when it happened, whether it came from the MCP server, the hosted API, or a local server, the design text, and the precedents that were returned. The log is not part of the public repository.

On this machine the lines are in `data/usage.jsonl`. The hosted log is the private store [reg4rwe-usage](https://vercel.com/sajan-khoslas-projects/~/stores/blob/store_SZsHbbvd9d33zuo0). Connect that store to the **reg4rwe** project so production receives `BLOB_READ_WRITE_TOKEN`, then read both logs with:

```bash
vercel env pull .env.local --yes --project reg4rwe
python3 pipeline/usage_report.py
```

## What the layers are

1. **How the evidence was used.** Pivotal or substantial evidence, supportive or contextual evidence, safety and labelling, other uses, an unclear role, or no RWE content.
2. **What question it was asked to answer.** Post-approval safety and labelling, benefit–risk including external comparators, disease context, support to a clinical trial, other, or none.
3. **The setting.** Pregnancy, paediatric use, vaccines, rare disease, REMS, class warnings, oncology. A document can sit in more than one.
4. **What the regulator accepted or criticised.** Tags read from the assessment, the methodological issues, and the extracted passage.

## Rebuild the corpus

`data/corpus.json` is the published corpus. `pipeline/build_corpus.py` rebuilds it from the curated extracts in `data/curated/` and the screen in `data/search_update/`. `pipeline/locate_documents.py` attaches the public review or assessment-report link and the page. `pipeline/update_search.py` repeats the public screen and needs `pypdf` plus network access. Downloaded PDFs stay in `data/cache/` and are not part of this repository.
