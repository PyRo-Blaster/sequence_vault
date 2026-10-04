/** Chinese interface copy. Codes from the API map to labels here, in one place. */

export const taskStatus: Record<string, string> = {
  UPLOADED: "已上传",
  SCANNING: "安全扫描中",
  PARSING: "解析中",
  EXTRACTING: "提取中",
  VALIDATING: "校验中",
  REVIEW_READY: "待审核",
  COMPLETED: "已完成",
  FAILED: "失败",
  CANCELLED: "已取消",
  UNSUPPORTED: "不支持的格式",
};

export const candidateStatus: Record<string, string> = {
  DRAFT: "草稿",
  NEEDS_REVIEW: "待审核",
  BLOCKED: "已阻断",
  APPROVED: "已批准",
  COMMITTED: "已入库",
  REJECTED: "已拒绝",
  PENDING_CONTENT: "待补充内容",
  ARCHIVED: "已归档",
  SUPERSEDED: "已被新提取取代",
};

export const severity: Record<string, string> = { INFO: "提示", REVIEW: "需确认", BLOCK: "阻断" };

export const rules: Record<string, string> = {
  QC01: "序列为空或证据引用越界",
  QC02: "空白、换行或大小写已规范化",
  QC03: "含数字、非法符号或形近字符",
  QC04: "含扩展残基 B Z J X U O",
  QC05: "含省略号、截断或缺失片段",
  QC06: "含星号、间隔符或编号",
  QC07: "名称冲突或对应关系不明确",
  QC08: "来源含未完全读取的内容",
  QC09: "同名记录已有不同序列",
  QC10: "库中已有相同序列",
  QC11: "分子类型不确定",
};

export const resolutions: Record<string, string> = {
  correct_evidence_reference: "修正证据引用",
  mark_pending_content: "标记为待补充内容",
  automatic_normalization: "接受自动规范化",
  correct_input: "修正输入",
  apply_position_numbering_rule: "按位置编号规则处理",
  provide_source: "补充原始资料",
  confirm_residue_semantics: "已确认残基含义",
  re_extract: "重新提取",
  register_fragment: "登记为片段",
  apply_explicit_transformation: "执行明确的转换",
  select_name: "已确认名称",
  split_candidate: "拆分候选",
  reassociate_name: "重新对应名称",
  confirm_source_reviewed: "已核对原始文件",
  reparse_with_selected_view: "按所选视图重新解析",
  create_new_version: "创建新版本",
  rename: "改名",
  cancel: "取消入库",
  reuse_entity: "复用已有序列",
  confirm_molecule_type: "确认为蛋白质",
  reject: "拒绝",
};

export const nameSource: Record<string, string> = {
  fasta_header: "FASTA 标题",
  table_cell: "表格单元格",
  heading: "段落标题",
  filename: "文件名",
  manual: "手工输入",
  legacy_import: "旧系统导入",
};

export const origin: Record<string, string> = {
  extracted: "提取",
  manual_revision: "人工修订",
  legacy_import: "旧系统导入（无原文证据）",
};

export const completeness: Record<string, string> = {
  complete: "完整",
  fragment: "片段",
  unknown: "未确定",
};

export const failure: Record<string, string> = {
  infected: "安全扫描发现威胁，文件已隔离",
  scan_unavailable: "安全扫描服务不可用，已按安全策略停止",
  parse_unavailable: "解析服务暂时不可用",
  undecodable_text: "无法识别文本编码",
  parser_timeout: "解析超时",
  parser_crash: "解析器异常退出",
  parser_memory_limit: "解析超出内存限制",
  candidate_limit: "候选数量超过上限（每文件 1000 条）",
  no_sequences_found: "文件中未找到序列或可识别的名称",
  sequences_not_extracted: "文件中有类似序列的文字，但无法可靠提取；请改用 FASTA 或表格整理后上传",
  sequence_limit: "单条序列超过长度上限（100,000 残基）",
  corrupt_document: "文件已损坏、加密或格式不受支持",
  pdf_page_limit: "PDF 页数超过上限",
  parser_output_limit: "解析结果超过大小上限",
  extract_unavailable: "提取服务（模型）暂时不可用",
  stage_unavailable: "处理服务暂时不可用",
  invalid_document_ir: "解析结果不符合契约",
  invalid_extraction_result: "提取结果不符合契约",
  internal_error: "内部错误",
};

export const commitReason: Record<string, string> = {
  not_found: "未找到或无权访问",
  forbidden: "当前角色无入库权限",
  file_not_clean: "文件未通过安全扫描",
  task_cancelled: "任务已取消",
  superseded_run: "已被重新提取取代",
  stale_revision: "批准对应的版本已过期，请重新审核",
  qc_version_changed: "质控规则版本已更新，请重新校验",
  blocking_issues: "仍有阻断问题",
  sequence_limit: "序列超过长度上限（100,000 残基）",
  not_protein: "分子类型未确认为蛋白质",
  name_missing: "尚未选择名称",
  needs_version_decision: "同名记录需要明确的版本决定",
  version_cancelled: "审核人已选择取消入库",
  idempotency_key_reused: "幂等键已用于其他版本",
  concurrent_change: "与其他提交冲突，请重试",
  hash_collision: "哈希冲突，请联系管理员",
};

export const commitStatus: Record<string, string> = {
  COMMITTED: "已入库",
  ALREADY_COMMITTED: "此前已入库",
  CONFLICT: "冲突",
  FAILED: "失败",
};

export const errors: Record<string, string> = {
  revision_conflict: "该候选已被他人修改，请刷新后比较再操作。",
  unresolved_issues: "仍有需确认的问题未处理。",
  invalid_state: "当前状态不允许此操作。",
  resolution_not_allowed: "该问题不允许此处理方式。",
  forbidden: "您的项目角色不允许此操作。",
  not_found: "未找到或无权访问。",
  unauthenticated: "请先登录。",
  user_not_provisioned: "您的账号尚未开通，请联系项目管理员。",
  file_too_large: "文件超过大小上限。",
  unsupported_format: "不支持此文件类型。",
  checksum_mismatch: "上传内容与声明的大小或校验和不一致。",
  upload_complete: "上传已完成，不能再更改文件内容。",
  sequence_limit: "序列超过长度上限（100,000 残基）。",
  insecure_context:
    "当前页面不是 HTTPS 安全连接，浏览器无法计算文件校验和。请通过 HTTPS 访问本系统。",
  task_cancelled: "任务已取消。",
  rate_limited: "请求过于频繁，请稍后再试。",
  empty_file: "文件为空。",
  invalid_file_name: "文件名不可接受。",
  content_missing: "请先上传文件内容。",
  file_not_clean: "文件未通过安全扫描。",
  last_admin: "项目至少需要一名管理员。",
  unknown_user: "没有使用该登录名的已开通账号。",
  csrf_header_missing: "请求缺少安全标头，请刷新页面后重试。",
  malformed_request: "请求格式不正确，请检查输入。",
  invalid_request: "请求内容不正确。",
  revision_required: "缺少版本号，请刷新后重试。",
  idempotency_key_required: "缺少幂等键，请刷新后重试。",
  candidate_limit: "候选数量超过上限。",
  invalid_export: "旧系统导出文件格式不正确。",
  internal_error: "服务器内部错误，请稍后重试。",
  http_414: "检索条件过长。",
};

/** Server text (QC issue messages, parser coverage warnings) in Chinese. Each pattern mirrors
 * one English template in the backend; unknown text is shown as sent. */
const serverPatterns: [RegExp, (...groups: string[]) => string][] = [
  [/^The referenced text contains no residues\.$/, () => "引用的文本不含残基。"],
  [
    /^(remove_whitespace|uppercase): (\d+) position\(s\)\. (.*)$/,
    (op, n, reason) =>
      `${op === "uppercase" ? "转为大写" : "移除空白"}：${n} 处。${serverText(reason)}`,
  ],
  [/^Whitespace and line breaks are not residues\.$/, () => "空白和换行不是残基。"],
  [/^Residue letters are stored in upper case\.$/, () => "残基字母统一按大写存储。"],
  [/^Characters outside the protein alphabet: (.*)$/, (c) => `含蛋白质字母表以外的字符：${c}`],
  [/^Extended residue codes need confirmation: (.*)$/, (c) => `扩展残基代码需要确认：${c}`],
  [/^Ellipsis marks omitted residues\.$/, () => "省略号表示有残基被省略。"],
  [
    /^Stop or gap characters need an explicit transformation: (.*)$/,
    (c) => `终止符或间隔符需要明确的转换：${c}`,
  ],
  [
    /^Confirm the molecule type; only proteins can be published\.$/,
    () => "请确认分子类型；只有蛋白质序列可以入库。",
  ],
  [/^Extraction reported possible truncation\.$/, () => "提取结果提示序列可能被截断。"],
  [
    /^Name mapping is (\w+) with (\d+) candidate name\(s\)\.$/,
    (status, n) => `名称对应关系${association[status] ?? status}，候选名称 ${n} 个。`,
  ],
  [
    /^Parts of the source were not fully read; check the original\.$/,
    () => "原始文件有部分内容未完全读取，请核对原文。",
  ],
  [
    /^The sequence was joined from several blocks; confirm continuity\.$/,
    () => "序列由多个段落拼接而成，请确认连续性。",
  ],
  [
    /^An identical sequence is stored; it will be reused\.$/,
    () => "库中已有相同序列，入库时将复用。",
  ],
  [
    /^This name already has version (\d+) with a different sequence\.$/,
    (v) => `该名称已有版本 v${v}，且序列不同。`,
  ],
  [
    /^assembly orders must run 1\.\.(\d+) without gaps, got (\[[^\]]*\])$/,
    (n, got) => `拼接顺序必须为连续的 1..${n}，实际为 ${got}`,
  ],
  [/^no sequence spans$/, () => "没有序列片段"],
  [/^unknown block ('[^']*'|"[^"]*")$/, (b) => `未知段落 ${b}`],
  [
    /^span \[(\d+), (\d+)\) is outside block ('[^']*'|"[^"]*") of length (\d+)$/,
    (a, b, block, n) => `片段 [${a}, ${b}) 超出段落 ${block}（长度 ${n}）`,
  ],
  [/^overlapping spans in block ('[^']*'|"[^"]*")$/, (b) => `段落 ${b} 中的片段重叠`],
  [
    /^Tracked changes \((\d+)\) are shown with (original text|changes accepted); choose the view to use before approving\.$/,
    (n, view) =>
      `含 ${n} 处修订，当前按「${view === "original text" ? "原文" : "接受修订后"}」显示；批准前请选择要使用的视图。`,
  ],
  [
    /^(\d+) text box\(es\) were read outside the body order\.$/,
    (n) => `${n} 个文本框不在正文顺序中，已单独读取。`,
  ],
  [/^(\d+) hidden text run\(s\) were not read\.$/, (n) => `${n} 段隐藏文字未读取。`],
  [
    /^(\d+) image\(s\) were not read; OCR is not available yet\.$/,
    (n) => `${n} 张图片未读取（暂不支持 OCR）。`,
  ],
  [/^Embedded objects were not read\.$/, () => "嵌入对象未读取。"],
  [
    /^(\d+) merged (?:table cell\(s\)|cell range\(s\)); check row and column pairing\.$/,
    (n) => `${n} 处合并单元格，请核对行列对应关系。`,
  ],
  [/^Headers and footers were not read\.$/, () => "页眉和页脚未读取。"],
  [/^Comments were not read\.$/, () => "批注未读取。"],
  [/^Footnotes and endnotes were not read\.$/, () => "脚注和尾注未读取。"],
  [
    /^(\d+) formula cell\(s\) were not evaluated; cached values need review\.$/,
    (n) => `${n} 个公式单元格未重新计算，缓存值需要核对。`,
  ],
  [/^Hidden worksheets were read: (.*)\.$/, (names) => `已读取隐藏工作表：${names}。`],
  [
    /^Hidden rows \((\d+)\) and columns \((\d+)\) were read\.$/,
    (r, c) => `已读取隐藏的行（${r}）和列（${c}）。`,
  ],
  [/^Scanned page\(s\) without text were not read: (.*)\.$/, (p) => `无文字的扫描页未读取：${p}。`],
  [
    /^Possible multi-column layout on page\(s\) (.*); check reading order\.$/,
    (p) => `第 ${p} 页可能为多栏排版，请核对阅读顺序。`,
  ],
  [
    /^Text before the first FASTA header was not treated as a record\.$/,
    () => "第一个 FASTA 标题之前的文字未作为记录处理。",
  ],
  [
    /^Some blocks contain residue-like text that was not extracted\.$/,
    () => "部分段落含有类似序列的文字，但未被提取。",
  ],
  [
    /^(\d+) detected sequence\(s\) were not assigned to any record; check the original\.$/,
    (n) => `${n} 条检测到的序列未对应到任何记录，请核对原文。`,
  ],
  [
    /^Model assistance was not used \((.*)\); rule-based results shown\.$/,
    (problem) => `未使用模型辅助（${problem}），显示的是规则提取结果。`,
  ],
];

const association: Record<string, string> = {
  unambiguous: "明确",
  ambiguous: "不明确",
  conflicting: "存在冲突",
};

export function serverText(text: string): string {
  // QC01 joins several span problems with "; ".
  const parts =
    text.includes("; ") && !serverPatterns.some(([p]) => p.test(text)) ? text.split("; ") : [text];
  return parts
    .map((part) => {
      for (const [pattern, render] of serverPatterns) {
        const match = pattern.exec(part);
        if (match) return render(...match.slice(1));
      }
      return part;
    })
    .join("；");
}

export function errorText(error: unknown): string {
  if (error && typeof error === "object" && "code" in error) {
    const { code, message } = error as { code: string; message: string };
    return errors[code] ?? serverText(message);
  }
  return error instanceof Error ? error.message : "操作失败";
}
