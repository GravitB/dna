import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import Helix3D, { marksFromSegments, webglAvailable } from "./Helix3D";

afterEach(cleanup);

describe("3D helix", () => {
  it("maps alignment damage onto positions of the clean strand", () => {
    expect(
      marksFromSegments([
        { op: "equal", clean: "AC", read: "AC" },
        { op: "replace", clean: "G", read: "T" },
        { op: "insert", clean: "", read: "AA" },
        { op: "delete", clean: "TT", read: "" },
        { op: "equal", clean: "A", read: "A" },
      ]),
    ).toEqual([
      { index: 2, kind: "sub" },
      { index: 3, kind: "ins" },
      { index: 3, kind: "del" },
      { index: 4, kind: "del" },
    ]);
  });
  it("explains itself instead of drawing anything when WebGL is unavailable", () => {
    expect(webglAvailable()).toBe(false); // jsdom has no WebGL
    render(<Helix3D sequence="ACGT" label="3D model of strand 1" />);
    expect(screen.getByRole("img", { name: "3D model of strand 1" })).toBeTruthy();
    expect(screen.getByText(/needs WebGL/)).toBeTruthy();
  });
});
