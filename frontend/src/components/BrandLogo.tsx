import logo from "../assets/logoKek.png";

export function BrandLogo({ className }: { className?: string }) {
  return <img src={logo} alt="Антидоброкек" className={className} />;
}
