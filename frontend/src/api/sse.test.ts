import { readSSE, SSEParser, type SSEMessage } from "./sse";

const FRAME =
  'id: 1\nevent: run.started\ndata: {"type":"run.started","seq":1}\n\n' +
  ": ping\n\n" +
  'id: 2\nevent: message.delta\ndata: {"type":"message.delta","text":"Hi"}\n\n';

function feedAll(chunks: string[]): SSEMessage[] {
  const parser = new SSEParser();
  return [...chunks.flatMap((c) => parser.feed(c)), ...parser.end()];
}

describe("SSEParser", () => {
  it("parses events and skips comments", () => {
    expect(feedAll([FRAME])).toEqual([
      { event: "run.started", data: '{"type":"run.started","seq":1}', id: "1" },
      { event: "message.delta", data: '{"type":"message.delta","text":"Hi"}', id: "2" },
    ]);
  });

  it("is independent of how the stream is chunked", () => {
    const whole = feedAll([FRAME]);
    for (let size = 1; size <= 7; size++) {
      const chunks: string[] = [];
      for (let i = 0; i < FRAME.length; i += size) chunks.push(FRAME.slice(i, i + size));
      expect(feedAll(chunks)).toEqual(whole);
    }
  });

  it("handles CRLF line endings, including a CR/LF pair split across chunks", () => {
    const crlf = FRAME.replace(/\n/g, "\r\n");
    expect(feedAll([crlf])).toEqual(feedAll([FRAME]));
    const cut = crlf.indexOf("\r\n") + 1; // split between \r and \n
    expect(feedAll([crlf.slice(0, cut), crlf.slice(cut)])).toEqual(feedAll([FRAME]));
  });

  it("joins multi-line data with newlines and strips one leading space", () => {
    expect(feedAll(["event: x\ndata: line one\ndata:  two\ndata\n\n"])).toEqual([
      { event: "x", data: "line one\n two\n", id: undefined },
    ]);
  });

  it("defaults the event name and flushes an unterminated final event", () => {
    expect(feedAll(["data: tail"])).toEqual([{ event: "message", data: "tail", id: undefined }]);
  });
});

describe("readSSE", () => {
  it("decodes UTF-8 split across byte chunks", async () => {
    const bytes = new TextEncoder().encode('event: message.delta\ndata: {"text":"café ✓"}\n\n');
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const b of bytes) controller.enqueue(new Uint8Array([b])); // one byte at a time
        controller.close();
      },
    });
    const out: SSEMessage[] = [];
    for await (const m of readSSE(stream)) out.push(m);
    expect(out).toHaveLength(1);
    expect(JSON.parse(out[0]!.data)).toEqual({ text: "café ✓" });
  });
});
