"use strict";

const fs = require("fs");
const vm = require("vm");

const html = fs.readFileSync(process.argv[2], "utf8");
const script = fs.readFileSync(process.argv[3], "utf8");
const plainText = (value) => value.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();

class Node {
  constructor(text, { after = null, children = [] } = {}) {
    this.innerText = text;
    this.textContent = text;
    this.after = after;
    this.children = children;
  }
  getClientRects() { return [1]; }
  querySelectorAll(selector) {
    if (["input", "textarea", "select", "input[type='file']"].includes(selector)) {
      return this.children;
    }
    return [];
  }
  click() {
    if (this.after) document.body.innerText += ` ${this.after}`;
  }
}

const buttons = [...html.matchAll(/<(button|a)([^>]*)>(.*?)<\/\1>/gis)].map((match) => {
  const after = match[2].match(/data-after=["']([^"']+)["']/i)?.[1] || null;
  return new Node(plainText(match[3]), { after });
});
const hasDialog = /role=["']dialog["']|class=["'][^"']*(?:boss-dialog|dialog-wrap|dialog-container)/i.test(html);
const hasField = /<(input|textarea|select)\b/i.test(html);
const dialog = hasDialog ? new Node("", { children: hasField ? [new Node("")] : [] }) : null;
const document = {
  location: { href: "https://www.zhipin.com/job_detail/fictional.html" },
  body: new Node(plainText(html)),
  documentElement: new Node(plainText(html)),
  querySelectorAll(selector) {
    if (selector === "button" || selector === "a") return buttons;
    if ([".boss-dialog", ".dialog-wrap", ".dialog-container", "[role='dialog']"].includes(selector)) {
      return dialog ? [dialog] : [];
    }
    return [];
  }
};

const context = {
  console,
  document,
  getComputedStyle: () => ({ display: "block", visibility: "visible" }),
  setTimeout: (callback) => { callback(); return 1; },
  clearTimeout: () => {}
};
context.globalThis = context;
vm.createContext(context);
vm.runInContext(script, context);

(async () => {
  const mode = process.argv[4] || "inspect";
  const result = mode === "execute"
    ? await context.JobPilotBossContact.executeBossContact(document)
    : context.JobPilotBossContact.inspectBossContactPage(document, mode === "after");
  process.stdout.write(JSON.stringify(result));
})().catch((error) => {
  process.stderr.write(error.stack || String(error));
  process.exit(1);
});
