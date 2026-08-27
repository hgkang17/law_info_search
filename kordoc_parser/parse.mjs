/**
 * stdin의 HWP/HWPX/PDF 바이트를 kordoc으로 읽어 JSON 한 줄을 stdout에 쓴다.
 * Python 도구가 Node 런타임 없이 파서를 재구현하지 않도록 이 파일만 호출한다.
 */
import { parse } from "kordoc"

const chunks = []
for await (const chunk of process.stdin) {
  chunks.push(chunk)
}
const buffer = Buffer.concat(chunks)

try {
  const result = await parse(buffer)
  const payload = result.success
    ? {
        success: true,
        fileType: result.fileType || "",
        markdown: result.markdown || "",
        isImageBased: Boolean(result.isImageBased),
        pageCount: result.pageCount || 0,
        error: "",
      }
    : {
        success: false,
        fileType: result.fileType || "",
        markdown: "",
        isImageBased: Boolean(result.isImageBased),
        pageCount: result.pageCount || 0,
        error: result.error || "파싱 실패",
      }
  process.stdout.write(JSON.stringify(payload))
} catch (error) {
  process.stdout.write(
    JSON.stringify({
      success: false,
      fileType: "",
      markdown: "",
      isImageBased: false,
      pageCount: 0,
      error: error instanceof Error ? error.message : String(error),
    }),
  )
  process.exitCode = 1
}
