import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QrScanner } from "../components/QrScanner";
import { reportToken } from "../utils/qr";
import { portal } from "./patient.helpers";
import { admin, mockFetch, respond } from "./helpers";
const token = "a".repeat(43);
const decode = vi.hoisted(() => ({ callback: undefined as any, stop: vi.fn(), canvas: vi.fn(), stream: vi.fn() }));
vi.mock("@zxing/browser", () => ({ BrowserQRCodeReader: class {
  decodeFromStream(...args: any[]) { decode.callback = args[2]; decode.stream(...args); return Promise.resolve({ stop: decode.stop }); }
  decodeFromCanvas = decode.canvas;
} }));
beforeEach(() => { decode.stop.mockClear(); decode.stream.mockClear(); decode.canvas.mockReset(); decode.callback = undefined; });
function camera() {
  Object.defineProperty(window, "isSecureContext", { configurable:true, value:true });
  const stop = vi.fn(); const getUserMedia = vi.fn().mockResolvedValue({ getTracks: () => [{ stop }] });
  Object.defineProperty(navigator, "mediaDevices", { configurable:true, value:{ getUserMedia } });
  return { stop, getUserMedia };
}
describe("safe QR input and scanner lifecycle", () => {
  it.each([token, `https://labchain.online/api/v1/verify/${token}`, `https://labchain.online/#/verify/${token}`, `https://www.labchain.online/api/v1/verify/${token}`])("accepts supported report input %s", value => expect(reportToken(value)).toBe(token));
  it.each([`https://evil.example/api/v1/verify/${token}`, `https://labchain.online.evil.example/api/v1/verify/${token}`, `http://labchain.online/api/v1/verify/${token}`, `https://user@labchain.online/api/v1/verify/${token}`, `https://labchain.online/api/v1/verify/${token}?redirect=evil`, `javascript:alert(1)`, "bad token", `https://labchain.online/api/v1/verify/${token}/compare`])("refuses external or ambiguous content %s", value => expect(reportToken(value)).toBeNull());
  it("opens camera only on request, rejects external QR, stops tracks on success and supports another scan", async () => {
    const { stop, getUserMedia } = camera(); const onToken=vi.fn(); render(<QrScanner onToken={onToken}/>);
    expect(getUserMedia).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", {name:"Start Camera"}));
    await waitFor(() => expect(decode.callback).toBeDefined());
    act(() => decode.callback({getText:()=>"https://evil.example"}));
    expect(screen.getByRole("alert")).toHaveTextContent("not a supported"); expect(onToken).not.toHaveBeenCalled();
    act(() => decode.callback({getText:()=>`https://labchain.online/api/v1/verify/${token}`}));
    expect(onToken).toHaveBeenCalledWith(token); expect(stop).toHaveBeenCalled(); expect(decode.stop).toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", {name:"Start Camera"}));
    await waitFor(() => expect(getUserMedia).toHaveBeenCalledTimes(2));
    await userEvent.click(screen.getByRole("button", {name:"Switch camera"}));
    await waitFor(() => expect(getUserMedia).toHaveBeenCalledWith(expect.objectContaining({video:expect.objectContaining({facingMode:{ideal:"user"}})})));
    await userEvent.click(screen.getByRole("button", {name:"Stop Camera"})); expect(screen.queryByLabelText("Live QR camera preview")).not.toBeInTheDocument();
  });
  it.each([['NotAllowedError','permission was denied'],['NotFoundError','No available camera'],['NotReadableError','No available camera']])("handles %s without leaking browser error", async (name,message) => {
    const {getUserMedia}=camera(); getUserMedia.mockRejectedValue(new DOMException("PRIVATE",name)); render(<QrScanner onToken={vi.fn()}/>);
    await userEvent.click(screen.getByRole("button",{name:"Start Camera"}));
    expect(await screen.findByRole("alert")).toHaveTextContent(message); expect(document.body).not.toHaveTextContent("PRIVATE");
  });
  it("stops a late camera permission response after unmount", async () => {
    const {getUserMedia,stop}=camera(); let resolve:any; getUserMedia.mockReturnValue(new Promise(r=>resolve=r));
    const view=render(<QrScanner onToken={vi.fn()}/>); await userEvent.click(screen.getByRole("button",{name:"Start Camera"}));
    await waitFor(()=>expect(getUserMedia).toHaveBeenCalled()); view.unmount();
    await act(async()=>resolve({getTracks:()=>[{stop}]})); expect(stop).toHaveBeenCalled();
  });
  it("offers fallbacks when camera APIs are unsupported", async () => {
    camera(); Object.defineProperty(window,"isSecureContext",{configurable:true,value:false}); render(<QrScanner onToken={vi.fn()}/>);
    await userEvent.click(screen.getByRole("button",{name:"Start Camera"})); expect(await screen.findByRole("alert")).toHaveTextContent("unavailable"); expect(screen.getByLabelText("Upload QR Image")).toBeEnabled();
  });
});
const evidence=()=>({status:"REGISTERED",message:"",report_code:"REP-001",version:1,checked_at:new Date().toISOString(),blockchain_checked_at:new Date().toISOString(),blockchain_evidence:"FOUR_PEER_VERIFIED",blockchain_verified_count:4,blockchain_peers:[1,2,3,4].map(i=>({peer:`peer${i}`,status:"VERIFIED",checked_at:new Date().toISOString()})),stored_artifact:"MATCH",issuer_evidence:"SNAPSHOT",document_comparison:"NOT_COMPARED",max_upload_bytes:10485760});
it("authorized personnel scan loads exact protected PDF alongside independent evidence and clears it on another scan",async()=>{
  vi.stubGlobal("URL",Object.assign(URL,{createObjectURL:vi.fn(()=>"blob:official"),revokeObjectURL:vi.fn()}));
  const fetch=mockFetch((p)=>p==='/api/v1/verify/staff/resolve'?respond({report_id:7,verification:evidence(),ledger_details_authorized:false,ledger_details:[]}):p==='/api/v1/reports/7/pdf'?new Response(new Blob(['%PDF-original'],{type:'application/pdf'})):undefined);
  portal('/reports/scan/'+token); expect(await screen.findByTitle('Official laboratory report PDF')).toHaveAttribute('src','blob:official#view=FitH&navpanes=0');
  expect(screen.getByText('All 4 blockchain peers confirmed matching report evidence.')).toBeVisible(); expect(screen.getByRole('link',{name:'Open full official PDF'})).toHaveAttribute('href','blob:official');
  expect(fetch).toHaveBeenCalledWith('/api/v1/verify/staff/resolve',expect.objectContaining({method:'POST',body:JSON.stringify({token})}));
  await userEvent.click(screen.getByText('Enter Verification Code')); await userEvent.type(screen.getByLabelText('Verification token'),'b'.repeat(43)); await userEvent.click(screen.getByRole('button',{name:'Check report'}));
  await waitFor(()=>expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:official'));
});
it('denies staff scanner without download permission and never fetches a private PDF',async()=>{
  const fetch=mockFetch(undefined,{...admin,roles:['LAB_STAFF'],permissions:['REPORT_READ']}); portal('/reports/scan/'+token);
  expect(await screen.findByRole('heading',{name:'Personnel report access required'})).toBeVisible();
  expect(fetch.mock.calls.some(([p])=>p.includes('/pdf')||p.endsWith('/resolve'))).toBe(false);
});
