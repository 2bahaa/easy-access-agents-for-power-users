/**
 * Incremental Server-Sent Events parser (WHATWG event-stream format).
 *
 * `EventSource` cannot send POST bodies, so the chat reads the response body of a
 * `fetch` and feeds decoded text chunks here. Chunks may split lines, fields or even
 * CRLF pairs anywhere; the parser buffers until a blank line completes an event.
 */

export interface SSEMessage {
  event: string;
  data: string;
  id?: string;
}

export class SSEParser {
  private buffer = "";
  private dataLines: string[] = [];
  private event = "";
  private id: string | undefined;

  /** Feed a chunk of text; returns the events completed by it. */
  feed(chunk: string): SSEMessage[] {
    this.buffer += chunk;
    const out: SSEMessage[] = [];
    // Split on CRLF, LF or CR. A trailing CR may be the first half of a CRLF split
    // across chunks, so keep it buffered.
    const lines = this.buffer.split(/\r\n|\n|\r(?!$)/);
    this.buffer = lines.pop() ?? "";
    for (const line of lines) this.processLine(line, out);
    return out;
  }

  /** Flush at end of stream (an unterminated final event is dispatched). */
  end(): SSEMessage[] {
    const out: SSEMessage[] = [];
    if (this.buffer) this.processLine(this.buffer.replace(/\r$/, ""), out);
    this.buffer = "";
    this.dispatch(out);
    return out;
  }

  private processLine(line: string, out: SSEMessage[]): void {
    if (line === "") {
      this.dispatch(out);
      return;
    }
    if (line.startsWith(":")) return; // comment / keep-alive
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "data") this.dataLines.push(value);
    else if (field === "event") this.event = value;
    else if (field === "id") this.id = value;
  }

  private dispatch(out: SSEMessage[]): void {
    if (this.dataLines.length > 0) {
      out.push({ event: this.event || "message", data: this.dataLines.join("\n"), id: this.id });
    }
    this.dataLines = [];
    this.event = "";
  }
}

/** Read a byte stream and yield parsed SSE messages. */
export async function* readSSE(body: ReadableStream<Uint8Array>): AsyncGenerator<SSEMessage> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const parser = new SSEParser();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      yield* parser.feed(decoder.decode(value, { stream: true }));
    }
    yield* parser.feed(decoder.decode());
    yield* parser.end();
  } finally {
    reader.releaseLock();
  }
}
