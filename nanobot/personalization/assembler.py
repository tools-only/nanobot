"""Compile selected exposure items into adaptive context blocks."""

from __future__ import annotations

from nanobot.personalization.contracts import ExposurePlan


class ExposureAssembler:
    """Assemble a selected slate into compact adaptive prompt blocks."""

    def build_blocks(self, plan: ExposurePlan) -> list[str]:
        blocks: list[str] = []
        profile_lines: list[str] = []
        evidence_lines: list[str] = []
        capability_lines: list[str] = []
        policy_lines: list[str] = []

        for item in plan.selected_items:
            if item.slot == "profile_summary":
                profile_lines.append(item.summary)
            elif item.surface == "context_evidence":
                evidence_lines.append(f"- {item.summary}")
            elif item.surface == "capability_exposure":
                capability_lines.append(f"- {item.summary}")
            else:
                policy_lines.append(f"- {item.summary}")

        if profile_lines:
            blocks.append("## User Profile Signal\n" + "\n".join(profile_lines))
        if evidence_lines:
            blocks.append("## Context Evidence\n" + "\n".join(evidence_lines))
        if capability_lines:
            blocks.append("## Capability Hints\n" + "\n".join(capability_lines))
        if policy_lines:
            blocks.append("## Interaction Policy\n" + "\n".join(policy_lines))
        return blocks
