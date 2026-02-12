from dataclasses import dataclass
from typing import Literal

from ..constants import ChecksumTypeAccession, ContactAccession, MzMLElement
from ..util import get_tag
from .dtree_wrapper import _DataTreeWrapper, _ParamGroup


@dataclass(frozen=True, repr=False)
class SourceFile(_ParamGroup):
    @property
    def id(self) -> str | None:
        return self.get_attribute("id")

    @property
    def name(self) -> str | None:
        return self.get_attribute("name")

    @property
    def location(self) -> str | None:
        return self.get_attribute("location")

    def __repr__(self) -> str:
        return f"SourceFile(id='{self.id}', name='{self.name}', location='{self.location}')"

    def __str__(self) -> str:
        return self.__repr__()

    @property
    def checksum_type(self) -> Literal["MD5", "SHA1", "SHA256"] | None:
        """Get checksum type if present."""
        for csa in ChecksumTypeAccession:
            if csa in self.accessions:
                match csa:
                    case ChecksumTypeAccession.MD5:
                        return "MD5"
                    case ChecksumTypeAccession.SHA1:
                        return "SHA1"
                    case ChecksumTypeAccession.SHA256:
                        return "SHA256"
        return None

    @property
    def checksum(self) -> str | None:
        """Get checksum value if present."""
        for param in self.cv_params:
            if param.accession in ChecksumTypeAccession:
                return param.value
        return None


@dataclass(frozen=True, repr=False)
class FileContent(_ParamGroup):
    pass


@dataclass(frozen=True, repr=False)
class Contact(_ParamGroup):
    @property
    def name(self) -> str | None:
        cv = self.get_cvparm(ContactAccession.NAME)
        return cv.value if cv else None

    @property
    def organization(self) -> str | None:
        cv = self.get_cvparm(ContactAccession.ORGANIZATION)
        return cv.value if cv else None

    @property
    def address(self) -> str | None:
        cv = self.get_cvparm(ContactAccession.ADDRESS)
        return cv.value if cv else None

    @property
    def url(self) -> str | None:
        cv = self.get_cvparm(ContactAccession.URL)
        return cv.value if cv else None

    @property
    def email(self) -> str | None:
        cv = self.get_cvparm(ContactAccession.EMAIL)
        return cv.value if cv else None

    @property
    def phone_number(self) -> str | None:
        cv = self.get_cvparm(ContactAccession.PHONE_NUMBER)
        return cv.value if cv else None

    @property
    def toll_free_phone_number(self) -> str | None:
        cv = self.get_cvparm(ContactAccession.TOLL_FREE_PHONE_NUMBER)
        return cv.value if cv else None

    @property
    def fax_number(self) -> str | None:
        cv = self.get_cvparm(ContactAccession.FAX_NUMBER)
        return cv.value if cv else None

    @property
    def role(self) -> str | None:
        cv = self.get_cvparm(ContactAccession.ROLE)
        return cv.value if cv else None

    def __repr__(self) -> str:
        s = "Contact("
        if name := self.name:
            s += f"name='{name}', "
        if organization := self.organization:
            s += f"organization='{organization}', "
        if address := self.address:
            s += f"address='{address}', "
        if url := self.url:
            s += f"url='{url}', "
        if email := self.email:
            s += f"email='{email}', "
        if phone_number := self.phone_number:
            s += f"phone_number='{phone_number}', "
        if toll_free_phone_number := self.toll_free_phone_number:
            s += f"toll_free_phone_number='{toll_free_phone_number}', "
        if fax_number := self.fax_number:
            s += f"fax_number='{fax_number}', "
        if role := self.role:
            s += f"role='{role}', "
        s = s.rstrip(", ") + ")"
        return s

    def __str__(self) -> str:
        return self.__repr__()


@dataclass(frozen=True)
class FileDescription(_DataTreeWrapper):
    @property
    def file_content(self) -> FileContent | None:
        """return file content as FileContent object if present"""
        fc_element = self.element.find(f"./{self.ns}{MzMLElement.FILE_CONTENT}")
        if fc_element is not None:
            return FileContent(element=fc_element)
        return None

    @property
    def source_files(self) -> list[SourceFile]:
        """return source files as tuple of SourceFile objects"""
        source_file_list = self.element.find(f"./{self.ns}{MzMLElement.SOURCE_FILE_LIST}")
        if source_file_list is not None:
            return [SourceFile(element=sf) for sf in source_file_list if get_tag(sf) == MzMLElement.SOURCE_FILE]
        return []

    def get_source_file(self, id: str) -> SourceFile | None:
        """Get a source file by ID (Accession or name)."""
        for sf in self.source_files:
            if sf.has_cvparm(id):
                return sf
        return None

    @property
    def contact(self) -> list[Contact]:
        """return a list of contacts if present"""
        contact_elements = self.element.findall(f"./{self.ns}{MzMLElement.CONTACT}")
        return [Contact(element=ce) for ce in contact_elements]

    def __repr__(self) -> str:
        return f"FileDescription(file_content={self.file_content}, \
        source_files={self.source_files}, contact={self.contact})"

    def __str__(self) -> str:
        return self.__repr__()
