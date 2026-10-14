/** Keep API responses uncacheable, including proxy errors and upstream headers. */
export function applyApiNoStore(response) {
  const writeHead = response.writeHead;
  response.setHeader("Cache-Control", "no-store");
  response.writeHead = function (statusCode, statusMessage, headers) {
    if (typeof statusMessage !== "string") {
      headers = statusMessage;
      statusMessage = undefined;
    }
    const isCacheHeader = key => /^(cache-control|expires)$/i.test(key);
    if (Array.isArray(headers)) {
      const filtered = [];
      for (let i = 0; i < headers.length; i += 2) {
        if (!isCacheHeader(headers[i])) filtered.push(headers[i], headers[i + 1]);
      }
      headers = filtered;
    } else if (headers) {
      headers = Object.fromEntries(Object.entries(headers).filter(([key]) => !isCacheHeader(key)));
    }
    this.removeHeader("Expires");
    this.setHeader("Cache-Control", "no-store");
    return statusMessage === undefined
      ? writeHead.call(this, statusCode, headers)
      : writeHead.call(this, statusCode, statusMessage, headers);
  };
}
