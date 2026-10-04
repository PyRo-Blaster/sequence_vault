import { errorText, serverText } from "./i18n";

describe("server text in Chinese (B6, B18)", () => {
  it("translates QC issue messages, keeping their details", () => {
    expect(serverText("Extended residue codes need confirmation: 'X' (U+0058)")).toBe(
      "扩展残基代码需要确认：'X' (U+0058)",
    );
    expect(
      serverText("remove_whitespace: 3 position(s). Whitespace and line breaks are not residues."),
    ).toBe("移除空白：3 处。空白和换行不是残基。");
    expect(serverText("Name mapping is conflicting with 2 candidate name(s).")).toBe(
      "名称对应关系存在冲突，候选名称 2 个。",
    );
    expect(serverText("This name already has version 3 with a different sequence.")).toBe(
      "该名称已有版本 v3，且序列不同。",
    );
  });

  it("translates each joined QC01 problem", () => {
    expect(serverText("unknown block 'p9'; span [0, 40) is outside block 'p1' of length 12")).toBe(
      "未知段落 'p9'；片段 [0, 40) 超出段落 'p1'（长度 12）",
    );
  });

  it("translates parser coverage warnings", () => {
    expect(serverText("2 image(s) were not read; OCR is not available yet.")).toBe(
      "2 张图片未读取（暂不支持 OCR）。",
    );
    expect(
      serverText(
        "Tracked changes (4) are shown with changes accepted; choose the view to use before approving.",
      ),
    ).toBe("含 4 处修订，当前按「接受修订后」显示；批准前请选择要使用的视图。");
  });

  it("maps error codes and falls back to translated text", () => {
    expect(errorText({ code: "empty_file", message: "The file is empty." })).toBe("文件为空。");
    expect(errorText({ code: "unmapped", message: "Comments were not read." })).toBe(
      "批注未读取。",
    );
    expect(serverText("Something new.")).toBe("Something new.");
  });
});
