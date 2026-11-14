import { lazy, Suspense, type ComponentProps } from "react";

const Helix3D = lazy(() => import("./Helix3D"));

/** Loads three.js only when a helix is actually on screen. */
export default function Helix(props: ComponentProps<typeof Helix3D>) {
  return (
    <Suspense fallback={<div className={`helix helix-loading${props.ambient ? " ambient" : ""}`} role="img" aria-label={props.label} />}>
      <Helix3D {...props} />
    </Suspense>
  );
}
