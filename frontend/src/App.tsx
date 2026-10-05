import type { AuthRedirect } from "./authRedirect";
import { CommitteeWorkspace } from "./CommitteeWorkspace";
import { CommitteeSignIn } from "./components/auth/CommitteeSignIn";
import { BrandLockup } from "./components/shared/BrandLockup";
import { HeaderAccount } from "./components/shared/HeaderAccount";
import { Toasts } from "./components/shared/Toasts";
import { EmailDeliveryAdvisory } from "./components/auth/EmailDelayNotice";
import { useSession } from "./hooks/useSession";
import { useToasts } from "./hooks/useToasts";

export function App(props: { authRedirect: AuthRedirect }) {
  const session = useSession(props.authRedirect);
  const { toasts, showError, dismissToast } = useToasts();

  if (session.user && !session.linkConflict) {
    return <CommitteeWorkspace key={session.user.id} user={session.user} logout={session.logout} />;
  }

  async function signOut(): Promise<void> {
    const error = await session.logout();
    if (error) showError(error);
  }

  return (
    <main className="app-shell">
      <header className="topnav">
        <div className="topnav-inner penta-header-inner">
          <BrandLockup />
          {session.user ? (
            <HeaderAccount email={session.user.email} role={session.user.role} onSignOut={() => void signOut()} />
          ) : null}
        </div>
      </header>
      <div className="page-heading"><h1>Penta Application Screener</h1></div>
      <CommitteeSignIn
        emailDeliveryNotice={<EmailDeliveryAdvisory />}
        emailSignInEnabled={session.emailSignInEnabled}
        isLoadingUser={session.isLoadingUser}
        userLoadRecovery={session.userLoadRecovery}
        signInState={session.signInState}
        linkConflict={session.linkConflict}
        linkedEmail={session.linkedEmail}
        onRequestLink={session.requestMagicLink}
        onKeepCurrent={session.keepCurrentSession}
        onOpenLinked={session.openLinkedSession}
        onEmailNew={session.emailNewLinkedSession}
        onRetryLink={session.retryLinkedSession}
        onReset={session.resetSignIn}
      />
      <Toasts toasts={toasts} onDismiss={dismissToast} />
    </main>
  );
}
