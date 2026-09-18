<?php

namespace App\Controller;

use App\Entity\Compte;
use App\Repository\CompteRepository;
use App\Repository\DepotRepository;
use App\Service\Boites;
use Symfony\Bundle\FrameworkBundle\Controller\AbstractController;
use Symfony\Component\HttpFoundation\BinaryFileResponse;
use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\HttpFoundation\Response;
use Symfony\Component\Routing\Attribute\Route;

/**
 * Boite aux lettres entre l'iPhone et l'application de bureau.
 *
 *   GET    /                   page d'envoi (la cle est dans le fragment #cle=...)
 *   POST   /api/depot          corps = fichier audio ; ?nom= &titre= ; cle d'envoi
 *   GET    /api/verifier       {utilisateur, type} ; l'une ou l'autre cle
 *   GET    /api/boite          depots en attente ; cle de retrait
 *   GET    /api/boite/{id}     telecharge un depot ; cle de retrait
 *   DELETE /api/boite/{id}     supprime un depot ; cle de retrait
 *
 * Cle : en-tete "Authorization: Bearer <cle>", ou ?cle=<cle> pour les raccourcis iPhone.
 */
class RelaisController extends AbstractController
{
    public function __construct(
        private CompteRepository $comptes,
        private DepotRepository $depots,
        private Boites $boites,
    ) {
    }

    #[Route('/', methods: ['GET'])]
    public function page(): Response
    {
        $r = $this->render('page.html.twig');
        $r->headers->set('Referrer-Policy', 'no-referrer');

        return $r;
    }

    #[Route('/sante', methods: ['GET'])]
    public function sante(): JsonResponse
    {
        return $this->json(['ok' => true]);
    }

    #[Route('/api/verifier', methods: ['GET'])]
    public function verifier(Request $request): JsonResponse
    {
        [$compte, $type] = $this->identifier($request);
        if (!$compte) {
            return $this->refus();
        }

        return $this->json(['utilisateur' => $compte->getNom(), 'type' => $type]);
    }

    #[Route('/api/depot', methods: ['POST'])]
    public function depot(Request $request): JsonResponse
    {
        [$compte, $type] = $this->identifier($request);
        if (!$compte || $type !== 'envoi') {
            return $this->refus();
        }
        try {
            $depot = $this->boites->deposer(
                $compte,
                $request->getContent(true),
                (int) $request->headers->get('Content-Length', '0'),
                (string) $request->query->get('nom', ''),
                (string) $request->query->get('titre', ''),
                (string) $request->headers->get('Content-Type', ''),
            );
        } catch (\DomainException $e) {
            return $this->json(['erreur' => $e->getMessage()], 400);
        }

        return $this->json(['ok' => true, 'id' => $depot->getId(), 'taille' => $depot->getTaille()]);
    }

    #[Route('/api/boite', methods: ['GET'])]
    public function boite(Request $request): JsonResponse
    {
        [$compte, $type] = $this->identifier($request);
        if (!$compte || $type !== 'retrait') {
            return $this->refus();
        }

        return $this->json(array_map(fn ($d) => $d->versTableau(), $this->depots->enAttente($compte)));
    }

    #[Route('/api/boite/{id}', requirements: ['id' => '[A-Za-z0-9_-]+'], methods: ['GET', 'DELETE'])]
    public function fichier(Request $request, string $id): Response
    {
        [$compte, $type] = $this->identifier($request);
        if (!$compte || $type !== 'retrait') {
            return $this->refus();
        }
        $depot = $this->depots->findOneBy(['id' => $id, 'compte' => $compte]);
        if (!$depot) {
            return $this->json(['erreur' => 'Fichier introuvable.'], 404);
        }
        if ($request->isMethod('DELETE')) {
            $this->boites->supprimer($depot);

            return $this->json(['ok' => true]);
        }
        $r = new BinaryFileResponse($this->boites->chemin($depot));
        $r->headers->set('Content-Type', 'application/octet-stream');
        $r->headers->set('Cache-Control', 'no-store');

        return $r;
    }

    /** @return array{0: ?Compte, 1: ?string} */
    private function identifier(Request $request): array
    {
        $auth = (string) $request->headers->get('Authorization', '');
        $cle = str_starts_with(strtolower($auth), 'bearer ')
            ? trim(substr($auth, 7))
            : (string) $request->query->get('cle', '');

        return $this->comptes->identifier($cle);
    }

    private function refus(): JsonResponse
    {
        sleep(1);   // freine les essais de cles au hasard

        return $this->json(['erreur' => 'Clé invalide.'], 403);
    }
}
