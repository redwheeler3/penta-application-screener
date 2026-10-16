// The Node test runner supplies storage; deployed code uses Cloudflare's DurableObject.
export class DurableObject<T> {
  constructor(protected ctx: DurableObjectState, protected env: T) {}
}
