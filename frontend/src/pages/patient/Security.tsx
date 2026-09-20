import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { QRCodeSVG } from "qrcode.react";
import { api } from "../../api/client";
import { useAuth } from "../../auth/Auth";
import { usePatientSecurity } from "../../auth/PatientAccess";
import { PatientLogout } from "../../layouts/PatientShell";
import { Dialog, Title } from "../../components/UI";
import {
  PatientMessage,
  PublicShell,
  SensitiveForm,
  passwordField,
  totpField,
} from "./Shared";
import type { Enrollment, RecoveryResponse } from "../../types/patient";
export function RecoveryCodes({
  codes,
  onDone,
}: {
  codes: string[];
  onDone: () => Promise<void>;
}) {
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState<Error>();
  const urls = useRef<Set<string>>(new Set());
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => {
      window.removeEventListener("beforeunload", warn);
      for (const url of urls.current) URL.revokeObjectURL(url);
      urls.current.clear();
    };
  }, []);
  function download() {
    const blob = new Blob(
      [
        "RHU LabChain recovery codes\nKeep these codes private. Each code can be used once.\n\n" +
          codes.join("\n") +
          "\n",
      ],
      { type: "text/plain;charset=utf-8" },
    );
    const url = URL.createObjectURL(blob);
    urls.current.add(url);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "rhu-labchain-recovery-codes.txt";
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => {
      URL.revokeObjectURL(url);
      urls.current.delete(url);
    }, 1000);
    setMessage("Recovery codes downloaded. Store the file somewhere private.");
  }
  return (
    <section className="recovery-display">
      <h2>Save your recovery codes</h2>
      <p className="notice" role="status">
        Save these codes now. They cannot be viewed again.
      </p>
      <p>
        Each code lets you sign in once if you cannot use your authenticator.
        Keep them private, in a secure place you can access without your phone.
      </p>
      <ul className="recovery-codes" aria-label="One-time recovery codes">
        {codes.map((code) => (
          <li key={code}>
            <code>{code}</code>
          </li>
        ))}
      </ul>
      <div className="actions">
        <button
          type="button"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(codes.join("\n"));
              setMessage("Recovery codes copied. Keep your clipboard private.");
            } catch {
              setMessage(
                "Copy is unavailable. Download the codes or save them manually.",
              );
            }
          }}
        >
          Copy codes
        </button>
        <button type="button" onClick={download}>
          Download codes
        </button>
      </div>
      <p role="status" className="small">
        {message}
      </p>
      <label className="check">
        <input
          type="checkbox"
          checked={saved}
          onChange={(e) => setSaved(e.target.checked)}
        />
        I have saved my recovery codes securely.
      </label>
      <PatientMessage error={error} />
      <button
        className="primary"
        disabled={!saved || busy}
        onClick={async () => {
          setBusy(true);
          setError(undefined);
          try {
            await onDone();
          } catch (e) {
            setError(e as Error);
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "Finishing…" : "Continue"}
      </button>
    </section>
  );
}
export function MfaSetup() {
  const { refresh: refreshAuth } = useAuth();
  const { security, refresh } = usePatientSecurity();
  const navigate = useNavigate();
  const [enrollment, setEnrollment] = useState<Enrollment>();
  const [codes, setCodes] = useState<string[]>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error>();
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  async function start() {
    setBusy(true);
    setError(undefined);
    setEnrollment(undefined);
    try {
      const value = await api<Enrollment>("/patient/mfa/totp/enroll", {
        method: "POST",
      });
      if (active.current) setEnrollment(value);
    } catch (e) {
      if (active.current) setError(e as Error);
    } finally {
      if (active.current) setBusy(false);
    }
  }
  return (
    <PublicShell locked={!!codes}>
      <section className="card patient-auth-card patient-setup">
        <p className="eyebrow">PROTECT YOUR ACCOUNT</p>
        <h1>Set up your authenticator</h1>
        {codes ? (
          <RecoveryCodes
            codes={codes}
            onDone={async () => {
              await refreshAuth();
              await refresh();
              setCodes(undefined);
              navigate("/patient", { replace: true });
            }}
          />
        ) : security.totp_enabled ? (
          <>
            <p>Your authenticator is already enabled.</p>
            <Link className="button primary" to="/patient/security">
              Security settings
            </Link>
          </>
        ) : (
          <>
            <p>
              {security.mfa_required
                ? "An authenticator is required before you can access your reports."
                : "Add an authenticator to protect your reports."}{" "}
              You will use a password and a short code to sign in.
            </p>
            <PatientMessage error={error} context="security" />
            {!enrollment ? (
              <button className="primary" disabled={busy} onClick={start}>
                {busy ? "Preparing setup…" : "Start authenticator setup"}
              </button>
            ) : (
              <>
                <ol className="setup-instructions">
                  <li>
                    Open your authenticator app and choose to add an account.
                  </li>
                  <li>Scan this QR code, or enter the setup key manually.</li>
                  <li>Enter the six-digit code shown in the app to finish.</li>
                </ol>
                <div className="enrollment-qr">
                  <QRCodeSVG
                    value={enrollment.provisioning_uri}
                    title="Scan with your authenticator to add your RHU LabChain account"
                    size={224}
                    marginSize={4}
                    role="img"
                    aria-label="Authenticator setup QR code"
                  />
                </div>
                <label>
                  Manual setup key
                  <input
                    readOnly
                    value={enrollment.secret}
                    autoComplete="off"
                    aria-describedby="secret-help"
                  />
                </label>
                <p id="secret-help" className="small muted">
                  Keep this key private. It is only shown during this setup.
                </p>
                <SensitiveForm
                  fields={[totpField]}
                  submit="Confirm authenticator"
                  onSubmit={async (values) => {
                    const response = await api<RecoveryResponse>(
                      "/patient/mfa/totp/confirm",
                      { method: "POST", body: { code: values.code } },
                    );
                    if (active.current) {
                      setEnrollment(undefined);
                      setCodes(response.recovery_codes);
                    }
                  }}
                />
              </>
            )}
          </>
        )}
        {!codes && (
          <div className="setup-exit">
            <PatientLogout />
          </div>
        )}
      </section>
    </PublicShell>
  );
}
export function PatientSecurityPage() {
  const { security, refresh } = usePatientSecurity();
  const { clear } = useAuth();
  const navigate = useNavigate();
  const [modal, setModal] = useState<
    "regenerate" | "disable" | "password" | null
  >(null);
  const [codes, setCodes] = useState<string[]>();
  const [recovery, setRecovery] = useState(false);
  const [disableConfirmed, setDisableConfirmed] = useState(false);
  const endSession = (message: string) => {
    clear(message);
    navigate("/patient/login", { replace: true, state: { message } });
  };
  if (codes)
    return (
      <>
        <Title title="New recovery codes" eyebrow="ACCOUNT SECURITY" />
        <section className="card">
          <RecoveryCodes
            codes={codes}
            onDone={async () => {
              await refresh();
              setCodes(undefined);
            }}
          />
        </section>
      </>
    );
  return (
    <>
      <Title title="Account security" eyebrow="KEEP YOUR REPORTS PRIVATE" />
      <section className="card">
        <h2>Authenticator & recovery</h2>
        <dl className="details">
          <div>
            <dt>Authenticator required</dt>
            <dd>{security.mfa_required ? "Yes" : "No"}</dd>
          </div>
          <div>
            <dt>Authenticator enabled</dt>
            <dd>{security.totp_enabled ? "Yes" : "No"}</dd>
          </div>
          <div>
            <dt>This sign-in verified</dt>
            <dd>{security.mfa_verified_for_current_session ? "Yes" : "No"}</dd>
          </div>
          <div>
            <dt>Unused recovery codes</dt>
            <dd>{security.unused_recovery_codes}</dd>
          </div>
        </dl>
        {security.totp_enabled ? (
          <div className="actions">
            <button onClick={() => setModal("regenerate")}>
              Generate new recovery codes
            </button>
            <button
              className="danger"
              onClick={() => {
                setModal("disable");
                setRecovery(false);
                setDisableConfirmed(false);
              }}
            >
              Disable authenticator
            </button>
          </div>
        ) : (
          <Link className="button primary" to="/patient/setup-mfa">
            Set up authenticator
          </Link>
        )}
      </section>
      <section className="card">
        <h2>Password</h2>
        <p>
          Choose a password with at least 12 characters that you do not use
          elsewhere.
        </p>
        <button onClick={() => setModal("password")}>Change password</button>
      </section>
      {modal && (
        <Dialog
          title={
            modal === "regenerate"
              ? "Generate new recovery codes"
              : modal === "disable"
                ? "Disable authenticator"
                : "Change password"
          }
          onClose={() => setModal(null)}
        >
          {modal === "regenerate" ? (
            <>
              <p className="notice">
                Old unused recovery codes will stop working. Save the
                replacement codes before leaving this page.
              </p>
              <SensitiveForm
                fields={[passwordField, { ...totpField, name: "totp_code" }]}
                submit="Replace recovery codes"
                onSubmit={async (values) => {
                  const response = await api<RecoveryResponse>(
                    "/patient/mfa/recovery-codes/regenerate",
                    {
                      method: "POST",
                      body: {
                        password: values.password,
                        totp_code: values.totp_code,
                      },
                    },
                  );
                  setModal(null);
                  setCodes(response.recovery_codes);
                }}
              />
            </>
          ) : modal === "disable" ? (
            <>
              <p className="notice">
                Your current authenticator will be disabled and your sessions
                will end.{" "}
                {security.mfa_required
                  ? "You must set up an authenticator again before accessing reports."
                  : "You can set up a new authenticator after signing in again."}
              </p>
              {!disableConfirmed ? (
                <>
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={disableConfirmed}
                      onChange={(e) => setDisableConfirmed(e.target.checked)}
                    />
                    I understand and want to disable my authenticator.
                  </label>
                </>
              ) : (
                <>
                  <SensitiveForm
                    key={String(recovery)}
                    fields={[
                      passwordField,
                      recovery
                        ? {
                            name: "recovery_code",
                            label: "Recovery code",
                            maxLength: 128,
                          }
                        : { ...totpField, name: "totp_code" },
                    ]}
                    submit="Confirm disable authenticator"
                    onSubmit={async (values) => {
                      await api("/patient/mfa/disable", {
                        method: "POST",
                        body: {
                          password: values.password,
                          ...(recovery
                            ? { recovery_code: values.recovery_code }
                            : { totp_code: values.totp_code }),
                        },
                      });
                      endSession(
                        "Authenticator disabled. Please sign in again to set it up.",
                      );
                    }}
                  >
                    <div className="actions">
                      <button
                        type="button"
                        onClick={() => setRecovery(!recovery)}
                      >
                        {recovery
                          ? "Use authenticator code"
                          : "Use recovery code"}
                      </button>
                    </div>
                  </SensitiveForm>
                </>
              )}
            </>
          ) : (
            <SensitiveForm
              fields={[
                { ...passwordField, name: "current_password" },
                {
                  name: "new_password",
                  label: "New password",
                  type: "password",
                  autoComplete: "new-password",
                  minLength: 12,
                  maxLength: 1024,
                },
                {
                  name: "confirm_password",
                  label: "Confirm new password",
                  type: "password",
                  autoComplete: "new-password",
                  minLength: 12,
                  maxLength: 1024,
                },
              ]}
              submit="Update password"
              onSubmit={async (values) => {
                if (values.new_password !== values.confirm_password)
                  throw new Error(
                    "New passwords must match. Please enter them again.",
                  );
                await api("/auth/change-password", {
                  method: "POST",
                  body: {
                    current_password: values.current_password,
                    new_password: values.new_password,
                  },
                });
                endSession("Password updated. Please sign in again.");
              }}
            />
          )}
        </Dialog>
      )}
    </>
  );
}
