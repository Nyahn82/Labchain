import { useState } from "react";
import { api } from "../api/client";
import { useAuth } from "../auth/Auth";
import { Form } from "./Form";
import { Dialog } from "./UI";
import type { Row } from "../types/domain";
export function SpecimenGuidance({ specimen, done }: { specimen: Row; done?: () => void }) {
  const { can } = useAuth();
  const [editing, setEditing] = useState(false);
  const guidance = (specimen.collection_guidance || {}) as Row;
  return <section><h4>{String(specimen.sample_name)} · {String(specimen.specimen_code || "Legacy specimen")}</h4>
    <p>Container: {String(guidance.container || "Facility SOP required")}; additive: {String(guidance.anticoagulant || "Facility SOP required")}</p>
    <p>Handling: {String(guidance.handling || "Facility SOP required")}</p>
    <p>Rejection rules: {(guidance.rejection_rules as string[] || []).join("; ") || "Facility SOP required"}</p>
    <p>Review: {String(guidance.review_status || "Facility review required")}</p>
    {done && can("SAMPLE_TYPE_MANAGE") && <button onClick={() => setEditing(true)}>Configure {String(specimen.sample_name)} collection</button>}
    {editing && <Dialog title="Facility specimen collection guidance" onClose={() => setEditing(false)}><p>Enter validated local SOP instructions. Do not substitute specimen types or assume a container is suitable for every assay.</p><Form fields={[
      {name: "container", label: "Validated container", type: "textarea", max: 2000},
      {name: "anticoagulant", label: "Validated additive / anticoagulant", max: 2000},
      {name: "handling", label: "Validated collection and handling", type: "textarea", max: 2000},
      {name: "rejection", label: "Validated rejection rules (one per line)", type: "textarea", max: 4000},
    ]} initial={{...guidance, rejection: (guidance.rejection_rules as string[] || []).join("\n")}} onSubmit={async body => {
      await api(`/lab/sample-types/${specimen.sample_type_id}`, {method: "PATCH", body: {collection_guidance: {...guidance, container: body.container, anticoagulant: body.anticoagulant, handling: body.handling, rejection_rules: String(body.rejection || "").split("\n").map(s => s.trim()).filter(Boolean), review_status: "FACILITY_CONFIGURED"}}});
      setEditing(false); done?.();
    }} /></Dialog>}
  </section>;
}
