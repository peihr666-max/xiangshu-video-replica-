import "./brand-identity.css";

export function BrandIdentity() {
  return (
    <span className="brand-identity">
      <img src="/studio/logo-mark.svg" alt="众墅之家" />
      <span className="brand-identity__text">
        <strong>众墅之家</strong>
        <span>AI 即创</span>
      </span>
    </span>
  );
}
