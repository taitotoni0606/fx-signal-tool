from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LiveFilterSnapshot:
    bias: str
    score: int
    regime_name: str
    regime_bias: str
    regime_group: str
    session: str
    macro_bias: str
    event_level: str
    risk_reward: float | None
    warning_count: int


@dataclass(frozen=True)
class LiveFilterDecision:
    kind: str
    label: str
    reason: str
    effective_score: int
    main_threshold: int
    candidate_threshold: int
    notes: tuple[str, ...] = ()


class LiveFilterEngine:
    """Lightweight guardrail engine used only at live-notification time."""

    def decide(self, snapshot: LiveFilterSnapshot, config: dict[str, object]) -> LiveFilterDecision:
        main_threshold = int(config.get("score_threshold", 68))
        candidate_threshold = int(config.get("candidate_score_threshold", 50))
        allow_high_event = bool(config.get("notify_during_high_event", False))
        notes: list[str] = []

        if snapshot.bias not in {"buy", "sell"}:
            return LiveFilterDecision(
                kind="none",
                label="見送り",
                reason="売買方向なし",
                effective_score=snapshot.score,
                main_threshold=main_threshold,
                candidate_threshold=candidate_threshold,
            )

        if snapshot.event_level == "high" and not allow_high_event:
            return LiveFilterDecision(
                kind="none",
                label="見送り",
                reason="重要イベント前後",
                effective_score=snapshot.score,
                main_threshold=main_threshold,
                candidate_threshold=candidate_threshold,
                notes=("イベントリスクを優先",),
            )

        adjusted_main = main_threshold
        adjusted_candidate = candidate_threshold
        cap_to_candidate = False

        if snapshot.event_level == "medium":
            adjusted_main += 2
            notes.append("中程度イベントで本命条件を少し厳格化")

        if snapshot.session == "薄商い":
            adjusted_main += 5
            adjusted_candidate += 5
            notes.append("薄商い時間帯のため厳格化")

        if snapshot.regime_group == "中立/確認中":
            adjusted_main += 4
            adjusted_candidate += 3
            notes.append("相場環境が中立のため厳格化")
        elif snapshot.regime_group == "レンジ":
            adjusted_main += 3
            adjusted_candidate += 2
            notes.append("レンジ相場のだましを警戒")
        elif snapshot.regime_group == "ボラ拡大":
            adjusted_main += 2
            notes.append("ボラ拡大で滑りを警戒")

        if snapshot.regime_bias in {"buy", "sell"} and snapshot.regime_bias != snapshot.bias:
            adjusted_main += 8
            adjusted_candidate += 5
            cap_to_candidate = True
            notes.append("相場環境の方向と売買方向が不一致")

        if snapshot.macro_bias in {"buy", "sell"} and snapshot.macro_bias != snapshot.bias:
            adjusted_main += 6
            adjusted_candidate += 4
            notes.append("米金利方向と売買方向が不一致")

        if snapshot.risk_reward is not None:
            if snapshot.risk_reward < 1.15:
                return LiveFilterDecision(
                    kind="none",
                    label="見送り",
                    reason="リスクリワード不足",
                    effective_score=snapshot.score,
                    main_threshold=adjusted_main,
                    candidate_threshold=adjusted_candidate,
                    notes=tuple(notes + [f"RR {snapshot.risk_reward:.2f}"]),
                )
            if snapshot.risk_reward < 1.35:
                cap_to_candidate = True
                notes.append(f"リスクリワード控えめ RR {snapshot.risk_reward:.2f}")

        if snapshot.warning_count >= 3:
            adjusted_main += 3
            notes.append("注意点が多いため本命条件を厳格化")

        if snapshot.score >= adjusted_main and not cap_to_candidate:
            return LiveFilterDecision(
                kind="main",
                label="本命通過",
                reason=f"実戦条件通過 ({snapshot.score}% >= {adjusted_main}%)",
                effective_score=snapshot.score,
                main_threshold=adjusted_main,
                candidate_threshold=adjusted_candidate,
                notes=tuple(notes),
            )

        if snapshot.score >= adjusted_candidate:
            label = "候補に降格" if snapshot.score >= main_threshold else "候補通過"
            return LiveFilterDecision(
                kind="candidate",
                label=label,
                reason=f"候補条件通過 ({snapshot.score}% >= {adjusted_candidate}%)",
                effective_score=snapshot.score,
                main_threshold=adjusted_main,
                candidate_threshold=adjusted_candidate,
                notes=tuple(notes),
            )

        return LiveFilterDecision(
            kind="none",
            label="見送り",
            reason=f"実戦条件未満 ({snapshot.score}% < {adjusted_candidate}%)",
            effective_score=snapshot.score,
            main_threshold=adjusted_main,
            candidate_threshold=adjusted_candidate,
            notes=tuple(notes),
        )
