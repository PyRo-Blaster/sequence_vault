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
  sequence_limit: "单条序列超过长度上限（100,000 残基）",
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
  task_cancelled: "任务已取消。",
  rate_limited: "请求过于频繁，请稍后再试。",
};

export function errorText(error: unknown): string {
  if (error && typeof error === "object" && "code" in error) {
    const { code, message } = error as { code: string; message: string };
    return errors[code] ?? message;
  }
  return error instanceof Error ? error.message : "操作失败";
}
