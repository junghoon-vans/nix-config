---
name: jira-cloud-formatting
description: >-
  Draft and convert Jira Cloud rich-text content for editor paste, direct REST API v3 ADF fields, or a specifically supplied MCP tool schema. Use whenever someone asks to format a Jira issue/comment, convert Jira Wiki Markup, prepare a Jira payload, or make content paste-ready; Korean triggers include Jira 내용 포맷, 이슈 본문 작성, Jira에 붙여넣기, 위키 마크업 변환, and ADF로 변환. Do not assume Jira Server/Data Center behavior or that an MCP tool accepts ADF.
---

# Jira Cloud formatting

Help draft Jira Cloud descriptions, comments, and other rich-text content without confusing the editor's Markdown input, REST API document payloads, or an MCP tool's own schema. Follow the format of the destination, preserve the user's content, and return a draft by default.

## Choose the destination first

If the user has not specified a destination, default to **Jira Cloud editor paste** and say so. If they name an API or MCP tool, use that route instead. Ask only when the route or required schema is genuinely unclear.

### Jira Cloud editor paste

- Return the body in the user's language as copy-ready Markdown using only the editor's documented subset: headings, emphasis, strike-through, inline/fenced code, links, lists, quotes, and horizontal rules. Do not wrap the paste-ready body in a code fence in the final answer; use headings or a brief label to separate it from explanatory notes.
- Jira Cloud's rich-text editor converts supported Markdown as you type or paste. The editor is the conversion surface; inspect the result where exact structure matters. Do not emit Jira Wiki Markup as if it were Cloud editor syntax.
- Do not promise that Markdown tables or panel-like text will become Jira tables or panels on paste. For a real table or panel, tell the user to insert one with the editor toolbar or `/` slash-command menu, then provide the exact cell values or panel text to place into it. Preserve every heading, row, cell, and callout detail; do not silently flatten or discard content.
- Keep links and code literal where appropriate. Leave unsupported or ambiguous formatting readable rather than inventing behavior.

### Direct Jira REST API v3

- For a rich-text field that the specific endpoint supports as ADF, create an Atlassian Document Format (ADF) document object, not a Markdown string. ADF documents have a versioned `doc` root and ordered block/inline nodes. Match the endpoint and field schema; do not assume every Jira field or node accepts the same content.
- Return only the requested payload or field fragment. Do not fabricate project keys, issue IDs, account IDs, or other values the user did not provide.

Minimal field-fragment example (not a complete create-issue request):

```json
{
  "description": {
    "version": 1,
    "type": "doc",
    "content": [
      {
        "type": "paragraph",
        "content": [{ "type": "text", "text": "Login fails after password reset." }]
      }
    ]
  }
}
```

Use table or panel ADF nodes only when the target endpoint and field support them; schema presence alone is not proof of endpoint support.

### MCP tool

- Treat the named MCP tool's provided input schema and field descriptions as authoritative. Never assume an MCP tool accepts ADF or forwards input unchanged to Jira REST v3.
- Match both the schema and any format selector. A generic `string` type does not establish Markdown support; follow its description or use plain text. Some tools accept serialized ADF JSON in a string with `contentFormat: "adf"`; serialize the document there rather than passing an object. Pass an ADF object only when that input accepts an object. If a schema can be inspected through available tools, inspect it before asking the user; otherwise provide a draft without guessing a payload.
- Do not invent mention/account IDs. Keep a person's name as ordinary text unless a real mention can be resolved through the destination's UI or a verified identifier supplied by the user/tool.

## Convert Jira Wiki Markup as input only

Translate its meaning into the selected destination format; never reproduce legacy syntax as the Cloud output. For example, convert a Wiki heading such as `h2.` to a Markdown heading for editor paste, `{code}` blocks to fenced code, and `{{inline code}}` to single-backtick code. Convert `{panel}` content into preserved callout text and direct the user to insert a Jira panel in the editor when using paste. For Wiki tables, retain the headers and every cell as explicit data and have the user insert/populate an editor table; do not claim a Markdown pipe table will paste as one. When using REST ADF, represent structures with supported nodes only.

Keep any original labels, values, ordering, and code exactly unless the user asks for rewriting. If source markup is malformed or a value's meaning is unclear, preserve the raw value and note the ambiguity rather than guessing.

## Draft and posting boundary

Provide a draft only unless the user explicitly authorizes posting and identifies the destination. Drafting, formatting, or preparing a payload does not authorize a Jira write. If posting is explicitly requested, use only an available tool whose schema supports the requested operation, confirm missing target details instead of making them up, and submit only the authorized content.

## Minimal UI draft example

For a user who asks for a paste-ready bug description, provide a body like this (without the outer fence):

```markdown
## Summary
Password reset returns an error for an active account.

**Steps to reproduce**
1. Open the password reset page.
2. Submit a registered email address.

**Expected result**
A reset link is sent.

**Actual result**
The page displays `HTTP 500`.
```

## Official references

- [Markdown and keyboard shortcuts — Jira Cloud](https://support.atlassian.com/jira-software-cloud/docs/markdown-and-keyboard-shortcuts/)
- [Atlassian Document Format: document structure](https://developer.atlassian.com/cloud/jira/platform/apis/document/structure/)
