import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useResource } from "../api/useResource";
import { PermissionGuard, useAuth } from "../auth/Auth";
import { Action, Dialog, State, Table, Title } from "../components/UI";
import { Form, Lookup } from "../components/Form";
import { Details } from "../components/Details";
import type { Row } from "../types/domain";
import {
  field,
  resources,
  ranges,
  rules,
  sampleLookup,
  testsLookup,
} from "./resources";
import { ResourcePage } from "./ResourcePage";
export function Laboratory() {
  const { can } = useAuth();
  return (
    <>
      <Title title="Laboratory setup" />
      <p className="intro">
        Configure the catalog and approved reference information used by your
        laboratory.
      </p>
      <div className="setup-grid">
        {["departments", "samples", "tests", "panels", "reasons"]
          .filter((k) => can(resources[k].read))
          .map((k) => (
            <Link className="card setup-card" key={k} to={`/laboratory/${k}`}>
              <h2>{resources[k].title}</h2>
              <p>Manage {resources[k].title.toLowerCase()} →</p>
            </Link>
          ))}
        {can("LAB_MASTER_READ") && (
          <div className="card">
            <h2>Reference ranges & interpretation</h2>
            <p>
              Open a test to manage its numeric ranges, qualitative normal
              values, and approved interpretation text.
            </p>
            <Link to="/laboratory/tests">Find a test →</Link>
          </div>
        )}
      </div>
    </>
  );
}
export function LabDetail({ kind }: { kind: "tests" | "panels" }) {
  return (
    <PermissionGuard permission="LAB_MASTER_READ">
      <LabContent kind={kind} />
    </PermissionGuard>
  );
}
function LabContent({ kind }: { kind: "tests" | "panels" }) {
  const { id } = useParams();
  const { can } = useAuth();
  const config = resources[kind];
  const state = useResource<Row>(`${config.path}/${id}`);
  const [edit, setEdit] = useState(false);
  return (
    <>
      <Title
        title={String(
          state.data?.[kind === "tests" ? "test_name" : "panel_name"] ||
            config.title,
        )}
      >
        <Link to={`/laboratory/${kind}`}>All {kind}</Link>
        {can(config.update) && state.data && (
          <button onClick={() => setEdit(true)}>Edit metadata</button>
        )}
      </Title>
      <State {...state} />
      {state.data && (
        <>
          <section className="card">
            <Details
              row={state.data}
              fields={config.fields.map((f) => [f.name, f.label])}
            />
          </section>
          {kind === "tests" ? (
            <>
              <SampleMapping
                key={JSON.stringify(state.data.sample_types)}
                test={state.data}
                done={state.reload}
              />
              <section className="card">
                <p>
                  Numeric thresholds and qualitative normal values are separate
                  configuration fields. Values describe laboratory references,
                  not diagnoses.
                </p>
              </section>
              <ResourcePage resource={ranges(id!)} embedded />
              <ResourcePage resource={rules(id!)} embedded />
            </>
          ) : (
            <PanelComposition
              key={JSON.stringify(state.data)}
              panel={state.data}
              done={state.reload}
            />
          )}
        </>
      )}
      {edit && state.data && (
        <Dialog title="Edit metadata" onClose={() => setEdit(false)}>
          <Form
            fields={config.fields}
            initial={state.data}
            onSubmit={async (body) => {
              await api(`${config.path}/${id}`, { method: "PATCH", body });
              setEdit(false);
              state.reload();
            }}
          />
        </Dialog>
      )}
    </>
  );
}
function SampleMapping({ test, done }: { test: Row; done: () => void }) {
  const { can } = useAuth();
  const mappings = test.sample_types as Row[];
  const [ids, setIds] = useState<number[]>(
    mappings.map((m) => Number(m.sample_type_id)),
  );
  const [defaultId, setDefaultId] = useState(
    Number(mappings.find((m) => m.is_default)?.sample_type_id) || 0,
  );
  return (
    <section className="card">
      <h2>Allowed sample types</h2>
      {can("TEST_CATALOG_MANAGE") ? (
        <>
          <Lookup
            spec={sampleLookup}
            label="Allowed sample types"
            multiple
            value={ids}
            onChange={(v) => {
              const next = v as number[];
              setIds(next);
              if (!next.includes(defaultId)) setDefaultId(0);
            }}
          />
          <label>
            Default sample type
            <select
              value={defaultId}
              onChange={(e) => setDefaultId(Number(e.target.value))}
            >
              <option value={0}>No default</option>
              {ids.map((id) => (
                <option key={id} value={id}>
                  {String(
                    (
                      mappings.find((m) => m.sample_type_id === id)
                        ?.sample_type as Row
                    )?.sample_name || `Sample type #${id}`,
                  )}
                </option>
              ))}
            </select>
          </label>
          <Action
            label="Replace sample mapping"
            description="Save the complete allowed sample-type list for this test."
            run={() =>
              api(`/lab/tests/${test.test_id}/sample-types`, {
                method: "PUT",
                body: {
                  sample_types: ids.map((id) => ({
                    sample_type_id: id,
                    is_default: id === defaultId,
                  })),
                },
              })
            }
            onDone={done}
          />
        </>
      ) : (
        <Table
          rows={mappings}
          columns={[
            { key: "sample_type.sample_name", label: "Sample type" },
            {
              key: "is_default",
              label: "Default",
              render: (r) => (r.is_default ? "Default" : "—"),
            },
          ]}
        />
      )}
    </section>
  );
}
function PanelComposition({ panel, done }: { panel: Row; done: () => void }) {
  const { can } = useAuth();
  const editable = can("TEST_PANEL_MANAGE");
  const sections = panel.sections as Row[];
  const [items, setItems] = useState<Row[]>(
    (panel.tests as Row[]).map((r) => ({ ...r })),
  );
  const [section, setSection] = useState<Row | null | undefined>();
  const ids = items.map((r) => Number(r.test_id));
  const change = (id: number, key: string, v: unknown) =>
    setItems((rows) =>
      rows.map((r) => (r.test_id === id ? { ...r, [key]: v } : r)),
    );
  return (
    <>
      <section className="card">
        <div className="section-heading">
          <h2>Panel sections</h2>
          {editable && (
            <button onClick={() => setSection(null)}>New section</button>
          )}
        </div>
        <State empty={!sections.length} />
        <Table
          rows={sections}
          columns={[
            { key: "section_name", label: "Section" },
            { key: "sort_order", label: "Order" },
            { key: "is_active", label: "Status", badge: true },
          ]}
          actions={
            editable
              ? (r) => (
                  <button onClick={() => setSection(r)}>Edit section</button>
                )
              : undefined
          }
        />
      </section>
      <section className="card">
        <h2>Panel composition</h2>
        {editable && (
          <Lookup
            spec={testsLookup}
            label="Panel tests"
            multiple
            value={ids}
            onChange={(v) =>
              setItems(
                (v as number[]).map(
                  (id) =>
                    items.find((r) => r.test_id === id) || {
                      test_id: id,
                      section_id: null,
                      sort_order: items.length + 1,
                      is_required: true,
                    },
                ),
              )
            }
          />
        )}
        <Table
          rows={items}
          columns={[
            {
              key: "test_id",
              label: "Test",
              render: (r) =>
                String((r.test as Row)?.test_name || `Test #${r.test_id}`),
            },
            {
              key: "section_id",
              label: "Section",
              render: (r) =>
                editable ? (
                  <select
                    aria-label={`Section for test ${r.test_id}`}
                    value={String(r.section_id ?? "")}
                    onChange={(e) =>
                      change(
                        Number(r.test_id),
                        "section_id",
                        e.target.value ? Number(e.target.value) : null,
                      )
                    }
                  >
                    <option value="">No section</option>
                    {sections.map((s) => (
                      <option
                        key={String(s.section_id)}
                        value={String(s.section_id)}
                      >
                        {String(s.section_name)}
                      </option>
                    ))}
                  </select>
                ) : (
                  String(
                    sections.find((s) => s.section_id === r.section_id)
                      ?.section_name || "—",
                  )
                ),
            },
            {
              key: "sort_order",
              label: "Sort order",
              render: (r) =>
                editable ? (
                  <input
                    aria-label={`Sort order for test ${r.test_id}`}
                    type="number"
                    step="1"
                    value={String(r.sort_order)}
                    onChange={(e) =>
                      change(Number(r.test_id), "sort_order", e.target.value)
                    }
                  />
                ) : (
                  String(r.sort_order)
                ),
            },
            {
              key: "is_required",
              label: "Required",
              render: (r) =>
                editable ? (
                  <input
                    aria-label={`Required test ${r.test_id}`}
                    type="checkbox"
                    checked={!!r.is_required}
                    onChange={(e) =>
                      change(Number(r.test_id), "is_required", e.target.checked)
                    }
                  />
                ) : r.is_required ? (
                  "Required"
                ) : (
                  "Optional"
                ),
            },
          ]}
        />
        {editable && (
          <Action
            label="Save composition"
            description="Replace this panel’s test composition with the displayed selection, sections, ordering, and required flags."
            valid={items.every(
              (r) =>
                String(r.sort_order) !== "" &&
                Number.isInteger(Number(r.sort_order)),
            )}
            run={() =>
              api(`/lab/panels/${panel.panel_id}/tests`, {
                method: "PUT",
                body: {
                  tests: items.map((r) => ({
                    test_id: r.test_id,
                    section_id: r.section_id,
                    sort_order: Number(r.sort_order),
                    is_required: r.is_required,
                  })),
                },
              })
            }
            onDone={done}
          />
        )}
      </section>
      {section !== undefined && (
        <Dialog
          title={section ? "Edit section" : "New section"}
          onClose={() => setSection(undefined)}
        >
          <Form
            fields={[
              field("section_name", "Section name", { required: true }),
              field("sort_order", "Sort order", {
                type: "number",
                required: true,
                default: 1,
              }),
              field("is_active", "Active", { type: "boolean", default: true }),
            ]}
            initial={section || {}}
            onSubmit={async (body) => {
              await api(
                `/lab/panels/${panel.panel_id}/sections${section ? "/" + section.section_id : ""}`,
                { method: section ? "PATCH" : "POST", body },
              );
              setSection(undefined);
              done();
            }}
          />
        </Dialog>
      )}
    </>
  );
}
