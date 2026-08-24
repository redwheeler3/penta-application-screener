import { LogOut } from "lucide-react";

type HeaderAccountProps = {
  email: string | null;
  role?: "admin" | "member";
  onSignOut: () => void;
};

export function HeaderAccount({ email, role, onSignOut }: HeaderAccountProps) {
  return (
    <div className="header-account">
      {email ? (
        <span className="header-account-identity">
          <span className="header-account-email" title={email}>{email}</span>
          {role ? <small className="header-account-role">{role}</small> : null}
        </span>
      ) : null}
      <button
        className="icon-button"
        type="button"
        aria-label={email ? `Sign out ${email}` : "Sign out"}
        title="Sign out"
        onClick={onSignOut}
      >
        <LogOut size={16} />
      </button>
    </div>
  );
}
