// RFC 9457 problem+json is the backend's single error contract. Keep parsing at
// the HTTP boundary so formatting helpers and feature modules do not each invent
// their own response-body handling.
export type Problem = {
  type: string;
  title: string;
  status: number;
  code: string;
  detail?: string;
  instance?: string;
  [key: string]: unknown;
};

export async function readProblemBody(response: Response): Promise<Partial<Problem> | null> {
  try {
    return (await response.json()) as Partial<Problem>;
  } catch {
    return null;
  }
}

export function problemMessage(body: Partial<Problem> | null): string | null {
  return body?.detail ?? body?.title ?? null;
}

export async function readProblem(response: Response): Promise<string | null> {
  return problemMessage(await readProblemBody(response));
}
