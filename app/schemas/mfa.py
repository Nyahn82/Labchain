"""Explicit MFA input/output allowlists; credential fields are redacted in repr."""
from pydantic import Field, SecretStr, field_validator, model_validator
from app.schemas.identity import Input
from app.schemas.laboratory import Output


class TotpCode(Input):
    code: SecretStr = Field(min_length=6, max_length=6)

    @field_validator('code')
    @classmethod
    def digits(cls, value):
        if any(c not in '0123456789' for c in value.get_secret_value()):
            raise ValueError('Invalid code.')
        return value


class RecoveryCode(Input):
    recovery_code: SecretStr = Field(min_length=1, max_length=128)


class Regenerate(Input):
    password: SecretStr = Field(min_length=1, max_length=1024)
    totp_code: SecretStr = Field(min_length=6, max_length=6)


class Disable(Input):
    password: SecretStr = Field(min_length=1, max_length=1024)
    totp_code: SecretStr | None = Field(default=None, min_length=6, max_length=6)
    recovery_code: SecretStr | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode='after')
    def one_factor(self):
        if (self.totp_code is None) == (self.recovery_code is None):
            raise ValueError('Provide exactly one second factor.')
        return self


class PasswordChange(Input):
    current_password: SecretStr = Field(min_length=1, max_length=1024)
    new_password: SecretStr = Field(min_length=12, max_length=1024)


class SecurityStatus(Output):
    mfa_required: bool
    totp_enabled: bool
    mfa_verified_for_current_session: bool
    unused_recovery_codes: int


class Enrollment(Output):
    secret: str = Field(repr=False)
    provisioning_uri: str = Field(repr=False)


class RecoveryCodes(Output):
    recovery_codes: list[str] = Field(repr=False)


class Confirmed(RecoveryCodes):
    enabled: bool


class MfaRequired(Output):
    mfa_required: bool = True
    methods: list[str] = ['TOTP', 'RECOVERY_CODE']
