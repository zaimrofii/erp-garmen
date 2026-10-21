import { createElement } from "react";
import { describe, expect, it } from "vitest";
import { MarkdownContent } from "@/components/molecules/MarkdownContent";
import { htmlOf } from "../../helpers/react-tree";

function render(content: string): string {
  return htmlOf(createElement(MarkdownContent, { content }));
}

describe("MarkdownContent — render GFM aman", () => {
  it("bold **text** → <strong>", () => {
    expect(render("Scrap **naik** 2%")).toContain("<strong>naik</strong>");
  });

  it("italic *text* → <em>", () => {
    expect(render("Ini *penting*.")).toContain("<em>penting</em>");
  });

  it("heading # H1 dibatasi menjadi <h4>", () => {
    const html = render("# Judul");

    expect(html).toContain("<h4");
    expect(html).toContain("Judul");
    expect(html).not.toContain("<h1");
  });

  it("list - item → <ul><li>", () => {
    const html = render("- scrap naik\n- rework turun");

    expect(html).toContain("<ul");
    expect(html).toContain("<li>scrap naik</li>");
    expect(html).toContain("<li>rework turun</li>");
  });

  it("inline `code` → <code>", () => {
    const html = render("Pakai `mcp-analytics`.");

    expect(html).toContain("<code");
    expect(html).toContain("mcp-analytics");
  });

  it("code block → <pre><code>", () => {
    const html = render("```ts\nconst x = 1;\n```");

    expect(html).toContain("<pre");
    expect(html).toContain("<code");
    expect(html).toContain("const x = 1;");
  });

  it("link → target _blank + rel noopener", () => {
    const html = render("[Dokumen](https://example.com)");

    expect(html).toContain('href="https://example.com"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain("noopener");
    expect(html).toContain("noreferrer");
  });

  it("tabel GFM dirender", () => {
    const html = render("| Kode | Qty |\n|---|---|\n| A | 2 |");

    expect(html).toContain("<table");
    expect(html).toContain("<th");
    expect(html).toContain("A");
  });

  it("content kosong → null", () => {
    expect(render("")).toBe("");
  });

  it("HTML mentah tidak dirender sebagai tag", () => {
    const html = render("<script>alert(1)</script>");

    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;script&gt;");
  });
});
