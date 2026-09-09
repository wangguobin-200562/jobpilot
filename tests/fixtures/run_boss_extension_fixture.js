"use strict";

const fs = require("fs");
const vm = require("vm");

class FakeNode {
  constructor(text = null, href = null, children = {}, attrs = {}) {
    this.textContent = text;
    this.innerText = text;
    this.href = href;
    this.children = children;
    this.attrs = attrs;
  }
  querySelector(selector) {
    const values = this.children[selector] || [];
    return values[0] || null;
  }
  querySelectorAll(selector) {
    return this.children[selector] || [];
  }
  getAttribute(name) {
    return name === "href" ? this.href : (this.attrs[name] || null);
  }
}

const leaf = (text, href = null, visibleText = text) => {
  const node = new FakeNode(text, href);
  node.innerText = visibleText;
  return node;
};
const makeCard = (item) => new FakeNode(item.lines?.join("\n") || null, null, {
  ".company-name": item.company === undefined ? [] : [leaf(item.company)],
  ".job-name": item.job_title === undefined ? [] : [leaf(item.job_title)],
  ".job-area": item.location === undefined ? [] : [leaf(item.location)],
  ".salary": item.salary === undefined ? [] : [leaf(item.salary)],
  "a[href*='/job_detail/']": item.source_url === undefined ? [] : [leaf(null, item.source_url)],
  ".job-sec-text": item.jd_text === undefined
    ? []
    : [leaf(item.jd_text, null, item.jd_visible_text === undefined ? item.jd_text : item.jd_visible_text)]
});

const input = JSON.parse(fs.readFileSync(0, "utf8"));
const cards = input.cards.map(makeCard);
const active = Number.isInteger(input.active_index) ? cards[input.active_index] : null;
const rootChildren = {
  ".job-card-wrapper": cards,
  ".job-card-wrapper.active": active ? [active] : [],
  ".job-sec-text": input.detail_jd === undefined ? [] : [leaf(input.detail_jd)]
};
const document = new FakeNode(null, null, rootChildren);
document.location = { href: input.page_url || "https://www.zhipin.com/web/geek/jobs" };

const context = { console, URL };
context.globalThis = context;
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), context);
const result = context.JobPilotBossExtractor.extractBossPage(document, document.location.href);
process.stdout.write(JSON.stringify(result));
