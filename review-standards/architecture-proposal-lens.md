# architecture-proposal-lens

審架構提案、spec 或設計文件時用的懷疑式檢查。內容搬自搬遷前 `agents/architecture-critic.md` 的 Review lens 第一半（For architecture proposals），文字不改。

## 適用

角色：architecture-critic。審查對象是架構提案、spec、design 文件。派工 prompt 另指定 lens 或明說忽略這一組時，以 prompt 為準，這一組記為相關但沒套用並寫「派工指定」。其他角色不套用。

## For architecture proposals

- Does every service boundary correspond to a real domain seam, or is this
  microservices-for-the-resume?
- What's the simplest design that meets the stated requirements? How does
  the proposal compare?
- Which non-functional requirements (latency, throughput, consistency) are
  unstated, and does the design accidentally violate them?
- What's the data migration story? "We'll figure it out" is a finding.
- What happens when service X is down? Trace one failure mode end-to-end.
