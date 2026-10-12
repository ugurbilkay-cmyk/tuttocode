# Irish passport photo-code integration

**Current decision (12 October 2026): Irish codes are outsourced. The studio
exports the photo for a chosen external provider; independent Irish issuance is
not part of the present release. The research below records options for later.**

Research checked 12 October 2026. Irish code issuance is not yet implemented.
Irish passport photos can already be cropped, printed, saved and emailed using
the imported templates; other countries cannot receive online passport codes.

## What the primary sources establish

The [Irish Passport Service photo guidelines](https://api.ireland.ie/en/dfa/passports/photo-guidelines/)
identify Photo-Me and IDstation.online as participating photo-code providers in
Ireland and the UK. They also allow applicants to upload a photographer's JPEG.
The published digital requirements include at least 715 x 951 pixels, a maximum
of 9 MB and no digital enhancement. The imported Ireland Passport online template
already uses 715 x 951. Automatic enhancement defaults to off in this build.

[Entrust's Irish Passport Office case study](https://www.entrust.com/sites/default/files/documentation/casestudies/idv-irish-passport-cs.pdf)
describes agreements with photo-booth operators: applicants enter a reference
number and the photo is transferred from the operator's central server to the
Irish online application. This indicates a provider integration rather than the
UK's publicly documented short-URL/JWS protocol. The case study is historical;
it is not an onboarding specification.

[IDstation.online](https://www.idstation.online/default/Default) invites photo
retailers to join its network and documents country-specific upload authorization
and station licences. Its [contact page](https://www.idstation.online/default/Home/Contact)
provides a support form. This is an existing provider route to investigate, not
evidence that our custom application can upload through an undocumented API.

No public Irish provider API/onboarding specification was found in the official
and provider sources searched. This does not establish that no API is available.
The current HMPO key, endpoint and `tpcode.uk/XXXXXXXX` codes must not be treated
as Irish codes.

## Concrete routes to establish

1. Ask DPS/IDstation.online whether a custom AI photo station can use their
   existing approved Irish integration, and request the retailer/station onboarding
   process, upload API, credentials, testing environment, pricing and licensing.
2. Ask the [Irish Passport Service](https://api.ireland.ie/en/dfa/passports/contact-us/)
   to direct a new independent provider to the Passport Online technical integration
   team and supply provider approval requirements, code format, retrieval
   authentication, reference registration, sandbox and production acceptance tests.

Provider responses are needed before choosing between an existing provider
connection and a direct approved integration. No account, agreement or outgoing
message has been created as part of this research.

## Suggested enquiry text

We operate Tuttoprint, a passport-photo retailer in London, and are building a
custom photo station using AI face detection and our own photo storage/code
service. We would like to issue photo codes accepted by Irish Passport Online.
Can you direct us to the provider onboarding and technical integration process?
Please confirm whether custom software can connect directly or through an
existing approved provider, and provide the API specification, authentication,
code format, photo requirements, sandbox, approval tests and commercial terms.

## Implementation once a route is agreed

Use a separate Irish provider adapter and persist its provider/reference rather
than generating a local HMPO code. Issue only after the provider acknowledges
the upload/reference registration, preserve an immutable photo after issuance,
and print/email the accepted Irish reference. Validate success, failure, retries,
expiry, deletion and real retrieval by Irish Passport Online before enabling the
issue button. UK retrieval must retain its HMPO signature verification.
