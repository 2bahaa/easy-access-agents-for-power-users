import type { ReactNode } from "react";
import { Link, type LinkProps } from "react-router";

import { buttonClasses } from "./buttonStyles";

/** A router link styled as a button (avoids nesting <button> inside <a>). */
export function LinkButton({
  variant,
  size,
  icon,
  className,
  children,
  ...props
}: LinkProps & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
  icon?: ReactNode;
}) {
  return (
    <Link className={buttonClasses({ variant, size, className })} {...props}>
      {icon}
      {children}
    </Link>
  );
}
