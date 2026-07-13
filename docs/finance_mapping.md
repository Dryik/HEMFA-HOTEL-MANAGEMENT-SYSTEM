# Finance Mapping and Approval Gate

The bundled Odoo 19 source does not include a Libyan localization. Phase 3 cannot be accepted until the hotel's finance owner supplies and signs the following mapping.

| Area | Required decision | Approved value |
|---|---|---|
| Chart of accounts | Account codes/names/types for `l10n_ly_hemfa` | Pending finance approval |
| Sales taxes | Rates, price-included policy, accounts, tax grids | Pending finance approval |
| Hotel room revenue | Product/category income account | Pending finance approval |
| POS revenue | Department income accounts and tax mapping | Pending finance approval |
| Room-charge clearing | Reconciliation-enabled current asset account | Pending finance approval |
| Guest receivable | Standard guest receivable account | Pending finance approval |
| Agency receivable | Agency/company receivable account | Pending finance approval |
| Guest deposits | Posted-payment journal and receivable treatment | Pending finance approval |
| Agency advances | Posted-payment journal and receivable treatment | Pending finance approval |
| Cash journals | One journal per accepted currency/property | Pending finance approval |
| Bank journals | One journal per accepted currency | Pending finance approval |
| Manual FX | Authorized roles: Hotel Accountant and Hotel Manager | Locked |
| Refunds/credits | Credit note and approval policy | Pending finance approval |

Manual invoice FX uses Odoo 19's native `invoice_currency_rate`. Any manual change requires a reason and a chatter entry with the old rate, new rate, user, and timestamp.

The reserved `l10n_ly_hemfa` addon remains deliberately non-installable while
any row above is pending. Finance approval and the localization data/tests must
be delivered in the same reviewed change before that gate can be opened.
