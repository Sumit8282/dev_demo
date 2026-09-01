interface PortalLogoProps {
  size?: number;
}

function IsometricCube({
  cx,
  cy,
  w = 11,
  h = 6.5,
}: {
  cx: number;
  cy: number;
  w?: number;
  h?: number;
}) {
  const top = `${cx},${cy - h}`;
  const tr = `${cx + w / 2},${cy - h / 2}`;
  const br = `${cx + w / 2},${cy + h / 2}`;
  const bottom = `${cx},${cy + h}`;
  const bl = `${cx - w / 2},${cy + h / 2}`;
  const tl = `${cx - w / 2},${cy - h / 2}`;

  return (
    <g stroke="white" strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round">
      <path d={`M ${tl} L ${top} L ${tr} L ${br} L ${bottom} L ${bl} Z`} />
      <path d={`M ${cx} ${cy} L ${top}`} />
      <path d={`M ${cx} ${cy} L ${br}`} />
      <path d={`M ${cx} ${cy} L ${bl}`} />
    </g>
  );
}

export default function PortalLogo({ size = 40 }: PortalLogoProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 40 40"
      fill="none"
      aria-hidden="true"
      className="portal-logo"
    >
      <rect width="40" height="40" rx="9" fill="#1a7f37" />
      <IsometricCube cx={20} cy={13.5} />
      <IsometricCube cx={13.5} cy={24.5} />
      <IsometricCube cx={26.5} cy={24.5} />
    </svg>
  );
}
