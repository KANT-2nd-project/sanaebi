/* eslint-disable @typescript-eslint/no-require-imports -- Turbopack loader entry uses CommonJS. */
const { createHash } = require("node:crypto");
const tailwindLoader = require("@tailwindcss/turbopack");

// Tailwind keys its compiler cache by resource and checks filesystem mtimes.
// Turbopack can supply newer CSS before that mtime check invalidates the compiler.
// Include the actual input in the key so a transform never reuses older CSS.
module.exports = function tailwindWithContentKey(source) {
  const context = Object.create(this);
  Object.defineProperty(context, "resource", {
    value: `${this.resource}?sanaebi-css=${createHash("sha256").update(source).digest("hex")}`,
  });
  return tailwindLoader.call(context, source);
};
