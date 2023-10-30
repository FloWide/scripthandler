from typing import List, Optional
import pygit2 as git
from enum import Enum
import re
import os

class GitAnalyzeResults(str,Enum):
    UP_TO_DATE = 'Up to date'
    FAST_FORWARD = 'Fast Forward'
    MERGE_REQUIRED = 'Merge Required'
    MERGE_CONFLICT = 'Merge Conflict'
    MERGE_CONFLICT_LOCAL_HARD_RESET = "Merge conflict local hard reset"
    MERGE_CONFLICT_REMOTE_HARD_RESET = "Merge conflict remote hard reset"
    AUTO_MERGE = 'Auto merge'
    NO_ACTION = 'No action'


TAG_REF_REGEX = re.compile('^refs/tags/')

DEFAULT_SIGNATURE = git.Signature("API","api@flowide.net")


class GitCallback(git.RemoteCallbacks):
    
    def certificate_check(self, certificate, valid, host: str):
        return True

# Mixin class for git commands
class GitRepository:

    _git_repo: git.Repository

    git_remote_callbacks: git.RemoteCallbacks

    def git_pull(self,remote_name="origin",reset_on_merge_conflict = True,force_hard_reset_to_remote=False) -> GitAnalyzeResults:
        repo = self._git_repo
        branch = self._git_repo.head.shorthand
        
        for remote in repo.remotes:
            if remote.name == remote_name:
                remote.fetch(callbacks=GitRepository.git_remote_callbacks)
                try:
                    remote_master_id = repo.lookup_reference(f'refs/remotes/{remote.name}/{branch}').target
                except KeyError:
                    return GitAnalyzeResults.NO_ACTION
                merge_result, _ = repo.merge_analysis(remote_master_id)
                # Up to date, do nothing
                if merge_result & git.GIT_MERGE_ANALYSIS_UP_TO_DATE:
                    
                    return GitAnalyzeResults.UP_TO_DATE
                # We can just fastforward
                elif merge_result & git.GIT_MERGE_ANALYSIS_FASTFORWARD:
                    repo.checkout_tree(repo.get(remote_master_id))
                    master_ref = repo.lookup_reference(f'refs/heads/{branch}')
                    master_ref.set_target(remote_master_id)
                    repo.head.set_target(remote_master_id)
                    return GitAnalyzeResults.FAST_FORWARD
                elif merge_result & git.GIT_MERGE_ANALYSIS_NORMAL:
                    repo.merge(remote_master_id)
                    

                    if(repo.index.conflicts is not None):
                        if reset_on_merge_conflict:
                            repo.reset(repo.head.target,git.GIT_RESET_HARD)
                            return GitAnalyzeResults.MERGE_CONFLICT_LOCAL_HARD_RESET
                        elif force_hard_reset_to_remote:
                            repo.reset(remote_master_id,git.GIT_RESET_HARD)
                            return GitAnalyzeResults.MERGE_CONFLICT_REMOTE_HARD_RESET
                        return GitAnalyzeResults.MERGE_CONFLICT
                    user = git.Signature("AutoMerger","automerger@flowide.net") # TODO: figure out what signature to use
                    tree = repo.index.write_tree()
                    commit = repo.create_commit('HEAD',
                                                user,
                                                user,
                                                'Merge!',
                                                tree,
                                                [repo.head.target, remote_master_id])
                    repo.state_cleanup()
                    return GitAnalyzeResults.AUTO_MERGE
                else:
                    raise AssertionError('Unknown merge analysis result')
        return GitAnalyzeResults.NO_ACTION

    def git_add(self,path: str | List[str]):
        if isinstance(path,list):
            for p in path:
                self._git_repo.index.add(p)
        else:
            self._git_repo.index.add(path)
        self._git_repo.index.write()

    def git_add_all(self):
        self._git_repo.index.add_all()
        self._git_repo.index.write()

    def git_remove(self,path: str | List[str]):
        if isinstance(path,list):
            for p in path:
                self._git_repo.index.remove(p)
        else:
            self._git_repo.index.remove(path)
        self._git_repo.index.write()

    def git_remove_all(self):
        self._git_repo.index.remove_all()
        self._git_repo.index.write()

    def git_revert_files(self,paths: List[str]):
        self._git_repo.checkout_head(paths=paths,strategy=git.GIT_CHECKOUT_FORCE)

    def git_commit(self,signature: git.Signature = DEFAULT_SIGNATURE,message: str = ''):
        tree = self._git_repo.index.write_tree()
        parent, ref = self._git_repo.resolve_refish(refish=self._git_repo.head.name)
        current = git.Signature(
            signature.name,
            signature.email
        )
        self._git_repo.create_commit(
            ref.name,
            current,
            current,
            message,
            tree,
            [parent.oid]
        )

    def git_push(self,remote_name="origin",push_tags=False):
        tags = []
        if push_tags:
            for ref in self._git_repo.references:
                if ref.startswith('refs/tags/'):
                    tags.append(ref)
        
        parent, ref = self._git_repo.resolve_refish(refish=self._git_repo.head.name)
        remote: git.Remote = self._git_repo.remotes[remote_name]
        remote.push([ref.name,*tags],callbacks=GitRepository.git_remote_callbacks)

    def git_stash(self,signature:git.Signature = DEFAULT_SIGNATURE,include_untracked=True):
        self._git_repo.stash(signature,include_untracked=include_untracked)

    def git_stash_pop(self):
        if self._git_repo.references.get('refs/stash'):
            self._git_repo.stash_pop()

    def git_status(self):
        return self._git_repo.status()

    def git_create_branch(self,branch_name: str):
        commit = self._git_repo.revparse_single(str(self._git_repo.head.target))
        self._git_repo.create_branch(branch_name,commit)

    def git_checkout(self,ref_name: str):
        try:
            ref = self._git_repo.lookup_reference(f"refs/heads/{ref_name}") # try to lookup as branch
        except KeyError:
            ref = self._git_repo.lookup_reference(f"refs/tags/{ref_name}") # lookup as tag            
        if ref:
            self._git_repo.checkout(ref)

    def git_tag(self,tag: str,signature: git.Signature = DEFAULT_SIGNATURE,message: str = '',commit_oid: Optional[git.Oid] = None):
        oid = self._git_repo.create_tag(
            tag,
            commit_oid or self._git_repo.head.target,
            git.GIT_OBJ_COMMIT,
            signature,
            message
        )
        return self._git_repo[oid]

    def git_list_commits(self):
        commits = []
        for commit in self._git_repo.walk(self._git_repo.head.target, git.GIT_SORT_TIME):
            commits.append({
                "message": commit.message.strip(),
                "time": commit.commit_time,
                "author_name": commit.author.name,
                "author_email": commit.author.email,
                "sha":commit.hex
            })
        return commits

    def git_delete_tag(self,tag: str,on_remote=True,remote_name="origin"):
        parent,ref = self._git_repo.resolve_refish(tag)
        if on_remote:
            remote = self._git_repo.remotes[remote_name]
            remote.push([f":{ref.name}"],callbacks=GitRepository.git_remote_callbacks)
        ref.delete()

    def git_create_remote(self,remote: str,url: str,ignore_already_exists: bool =True):
        try:
            self._git_repo.remotes.create(remote,url)
        except ValueError as e:
            if not ignore_already_exists:
                raise e 

    def git_remote_analyze(self,remote_name: str = 'origin') -> GitAnalyzeResults:
        branch = self._git_repo.head.shorthand
        for remote in self._git_repo.remotes:
            if remote.name == remote_name:
                remote.fetch(callbacks=GitRepository.git_remote_callbacks)
                try:
                    remote_master_id = self._git_repo.lookup_reference(f'refs/remotes/{remote.name}/{branch}').target
                except KeyError:
                    return GitAnalyzeResults.NO_ACTION
                merge_result, _ = self._git_repo.merge_analysis(remote_master_id)
                if merge_result & git.GIT_MERGE_ANALYSIS_UP_TO_DATE:
                    return GitAnalyzeResults.UP_TO_DATE
                elif merge_result & git.GIT_MERGE_ANALYSIS_FASTFORWARD:
                    return GitAnalyzeResults.FAST_FORWARD
                elif merge_result & git.GIT_MERGE_ANALYSIS_NORMAL:
                    return GitAnalyzeResults.MERGE_REQUIRED
                else:
                    return GitAnalyzeResults.NO_ACTION
        return GitAnalyzeResults.NO_ACTION

    def git_state_cleanup(self):
        self._git_repo.state_cleanup()

    def git_get_head_shorthand(self):
        return self._git_repo.head.shorthand

    def git_get_branches(self):
        return self._git_repo.listall_branches()

    def git_get_tags(self):
        return [self._git_repo.references.get(r) for r in self._git_repo.references if TAG_REF_REGEX.match(r)]

    def git_get_stashes_length(self):
        return len(self._git_repo.listall_stashes())

    def ensure_root_commit(self):
        try:
            parent, ref = self._git_repo.resolve_refish(refish=self._git_repo.head.name) # tries to resolve head to a reference
            return  
        except git.GitError: # if we cannot resolve head to a valid refernce it means the repository has no commits
            self.git_add_all()
            tree = self._git_repo.index.write_tree()
            self._git_repo.create_commit(
                'HEAD', # we create this commit for 'HEAD' instead of explicitly setting reference
                DEFAULT_SIGNATURE,
                DEFAULT_SIGNATURE,
                'Initial commit',
                tree,
                [] # since this is the root commit it has no parent(s)
            )
            self.git_push()

    def git_copy_tagged_version(self,tag: str,to_folder: str):
        parent,ref = self._git_repo.resolve_refish(tag)
        oid = ref.target
        commit: git.Commit = parent
        index = git.Index()
        index.read_tree(commit.tree)
        for entry in index:
            entry: git.IndexEntry
            content = self._git_repo[entry.oid].read_raw()
            file_path = os.path.join(to_folder,entry.path)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path,'wb') as f:
                f.write(content)

    def git_get_tagged_file(self,tag: str,file: str):
        parent,ref = self._git_repo.resolve_refish(tag)
        oid = ref.target
        commit: git.Commit = parent
        index = git.Index()
        index.read_tree(commit.tree)
        for entry in index:
            if entry.path == file:
                return self._git_repo[entry.oid].read_raw().decode()
        return None

    def git_has_remote(self,remote: str):
        for r in self._git_repo.remotes:
            if r.name == remote:
                return True
        return False

    @staticmethod
    def git_clone(url: str,path: str) -> git.Repository:
        return git.clone_repository(url,path,callbacks=GitRepository.git_remote_callbacks)

    @staticmethod
    def git_discover_repository(path: str) -> git.Repository:
        return git.Repository(
            git.discover_repository(path)
        )

    @classmethod
    def set_git_credentials(cls,remote_callbacks: git.RemoteCallbacks):
        cls.git_remote_callbacks = remote_callbacks