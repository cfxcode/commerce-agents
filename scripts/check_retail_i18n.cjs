// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");
const ts = require("../examples/node_modules/typescript");

process.env.NODE_PATH = path.resolve(__dirname, "../examples/node_modules");
Module._initPaths();

// Run the actual pure TypeScript localization functions without adding a test runtime.
const compileTypeScript = (module, filename) => {
  const result = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true, jsx: ts.JsxEmit.ReactJSX },
    fileName: filename,
  });
  module._compile(result.outputText, filename);
};
require.extensions[".ts"] = compileTypeScript;
require.extensions[".tsx"] = compileTypeScript;

const { normalizedLocale, registerTranslations, setCurrentLocale, translate, translateDeep } = require("../examples/web-shared/i18n-core.ts");
const { formatMoney, formatDate, optionValuesLabel, plural } = require("../examples/web-shared/format.ts");
const dataDir = path.resolve(__dirname, "../examples/retail/data");
const dictionary = require("../examples/retail/data/locales/zh-CN.json");
const catalog = require("../examples/retail/data/catalog.json");
const policies = require("../examples/retail/data/policies.json");
registerTranslations(dictionary);

assert.equal(normalizedLocale("zh-TW"), "zh-CN");
assert.equal(normalizedLocale("en-US"), "en");
assert.equal(normalizedLocale("fr"), "en");
assert.equal(translate("Cart", "en"), "Cart");
assert.equal(translate("Cart", "zh-CN"), "购物车");

const source = {
  product_id: "AR-1001", status: "new", kind: "note", category: "home-kitchen", labels: ["new"],
  currency: "USD", tier: "ACME Subscription member", title: catalog.products[0].title, options: { size: ["queen"] },
  option_values: { size: "queen" }, nested: { content: policies.policies[0].content }, price: 79,
};
const chinese = translateDeep(source, "zh-CN");
assert.notEqual(chinese.title, source.title);
assert.match(chinese.title, /[\u3400-\u9fff]/);
assert.match(chinese.nested.content, /[\u3400-\u9fff]/);
for (const key of ["product_id", "status", "kind", "category", "labels", "currency", "tier", "options", "option_values", "price"]) {
  assert.deepEqual(chinese[key], source[key], `canonical field ${key} changed`);
}
assert.equal(translateDeep(source, "en"), source);
assert.equal(source.title, catalog.products[0].title, "localization mutated its source");

for (const product of catalog.products) {
  assert.match(dictionary[product.title] ?? "", /[\u3400-\u9fff]/, `untranslated product ${product.product_id}`);
}
for (const policy of policies.policies) {
  assert.match(dictionary[policy.title] ?? "", /[\u3400-\u9fff]/, `untranslated policy ${policy.policy_id}`);
  assert.match(dictionary[policy.content] ?? "", /[\u3400-\u9fff]/, `untranslated policy content ${policy.policy_id}`);
}

// New English fixture content must come with a translation. Technical ids, enums,
// brands and customer names remain canonical rather than becoming dictionary keys.
const skipped = new Set(["product_id", "listing_id", "order_id", "policy_id", "user_id", "campaign_id", "merchant_id", "insight_id", "status", "kind", "category", "labels", "brand", "name", "display_name", "operator", "currency", "image_url", "tracking_url", "url", "email", "phone", "variant_of", "options", "option_values", "metric", "date", "period", "compare_to", "opened_at", "placed_at", "delivered_at", "updated_at", "created_at", "id", "key"]);
function checkContent(value, key = "") {
  if (skipped.has(key)) return;
  if (Array.isArray(value)) return value.forEach((item) => checkContent(item, key));
  if (value && typeof value === "object") return Object.entries(value).forEach(([field, item]) => checkContent(item, field));
  if (typeof value === "string" && /[A-Za-z]/.test(value) && !/^(https?:\/\/|\/products\/|AR-|ORD-|\d{4}-\d{2}-\d{2})/.test(value)) {
    assert.equal(typeof dictionary[value], "string", `missing fixture translation: ${value}`);
    assert.ok(dictionary[value].trim(), `empty fixture translation: ${value}`);
  }
}
for (const filename of fs.readdirSync(dataDir).filter((name) => name.endsWith(".json") && !name.startsWith("."))) {
  checkContent(JSON.parse(fs.readFileSync(path.join(dataDir, filename), "utf8")));
}

setCurrentLocale("en");
const englishMoney = formatMoney(79, "USD");
assert.equal(plural(2, "order"), "2 orders");
setCurrentLocale("zh-CN");
assert.equal(plural(2, "order"), "2 个订单");
assert.notEqual(formatMoney(79, "USD"), englishMoney);
assert.ok(!formatMoney(79, "USD").includes("¥"), "locale changed the currency");
assert.match(formatDate("2026-09-16"), /2026.*9.*16/);
assert.match(optionValuesLabel({ option_values: { size: "queen" } }), /[\u3400-\u9fff]/);
assert.equal(translate("Get it by Tue, Sep 22"), "9月22日前送达");
assert.equal(translate("2026-09-19 (updated after a carrier delay; the original 2026-09-13 estimate was missed)"), "2026-09-19 (因承运商延迟而更新；原预计 2026-09-13 未能按时送达)");
assert.match(translate(`Returns on ${catalog.products[0].title} are running at 14%`, "zh-CN"), /14%/);
setCurrentLocale("en");

// Render the real card registries in both languages without a browser or live model.
// This catches untranslated static chrome alongside translated fixture payloads.
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const resolveFilename = Module._resolveFilename;
let appDirectory;
Module._resolveFilename = function (request, parent, ...rest) {
  if (request.startsWith("@/")) request = path.join(appDirectory, request.slice(2));
  return resolveFilename.call(this, request, parent, ...rest);
};
let cardCount = 0;
for (const app of ["storefront-web", "merchant-web"]) {
  appDirectory = path.resolve(__dirname, "../examples/retail", app);
  const { SHOWCASE } = require(path.join(appDirectory, "lib/showcase-fixtures.ts"));
  const Block = require(path.join(appDirectory, "components/generative/index.tsx")).default;
  for (const locale of ["en", "zh-CN"]) {
    setCurrentLocale(locale);
    for (const [component, payload] of Object.entries(SHOWCASE)) {
      const html = renderToStaticMarkup(React.createElement(Block, {
        block: translateDeep({ component, payload }, locale), status: "final", onPrefill: () => {},
      }));
      const text = html.replace(/<[^>]+>/g, " ");
      assert.ok(html.length > 50, `${app}/${component} did not render`);
      if (locale === "zh-CN") {
        assert.match(text, /[\u3400-\u9fff]/, `${app}/${component} has no Chinese text`);
        assert.ok(!/\b(Ready to check out|Subtotal|Approve|Before|After|Out of stock|No items to show)\b/.test(text), `${app}/${component} has untranslated chrome`);
      } else {
        assert.ok(!/[\u3400-\u9fff]/.test(text), `${app}/${component} changed the English fixtures`);
      }
      cardCount += 1;
    }
  }
}
Module._resolveFilename = resolveFilename;
setCurrentLocale("en");

console.log(`Retail i18n checks passed: ${catalog.products.length} products, ${policies.policies.length} policies, ${Object.keys(dictionary).length} content translations, ${cardCount} bilingual card renders.`);
